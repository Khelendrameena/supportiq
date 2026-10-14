"""Tenant isolation: the correctness-critical guarantee of the whole project.

Layer 1 (application): middleware + TenantAwareManager scope every query.
Layer 2 (database, Postgres only): RLS policies fail closed even for raw SQL.
"""
import pytest
from django.db import connection
from kb.models import KnowledgeBase
from tenants.models import Tenant, get_current_tenant, set_current_tenant


@pytest.mark.django_db
class TestApplicationLayerIsolation:
    def test_user_sees_only_own_tenant_kbs(self, client_a, client_b, tenant_a, tenant_b):
        set_current_tenant(tenant_a)
        KnowledgeBase.objects.create(tenant=tenant_a, name="Acme KB")
        set_current_tenant(tenant_b)
        KnowledgeBase.objects.create(tenant=tenant_b, name="Beta KB")

        names_a = {kb["name"] for kb in client_a.get("/api/kb/knowledge-bases/").json()["results"]}
        names_b = {kb["name"] for kb in client_b.get("/api/kb/knowledge-bases/").json()["results"]}
        assert names_a == {"Acme KB"}
        assert names_b == {"Beta KB"}

    def test_cross_tenant_detail_is_404(self, client_a, tenant_a, tenant_b):
        set_current_tenant(tenant_b)
        kb = KnowledgeBase.objects.create(tenant=tenant_b, name="Beta KB")
        resp = client_a.get(f"/api/kb/knowledge-bases/{kb.id}/")
        assert resp.status_code == 404  # not 403: tenants must not learn ids exist

    def test_create_kb_stamps_current_tenant(self, client_a, tenant_a):
        resp = client_a.post(
            "/api/kb/knowledge-bases/", {"name": "Via API"}, format="json"
        )
        assert resp.status_code == 201, resp.content
        set_current_tenant(tenant_a)
        kb = KnowledgeBase.objects.get(id=resp.json()["id"])
        assert kb.tenant_id == tenant_a.id

    def test_manager_fails_closed_without_tenant(self, tenant_a):
        set_current_tenant(tenant_a)
        KnowledgeBase.objects.create(tenant=tenant_a, name="Acme KB")
        # Simulate a code path that forgot to resolve the tenant.
        from tenants.models import clear_current_tenant

        clear_current_tenant()
        assert list(KnowledgeBase.objects.all()) == []

    def test_middleware_rejects_foreign_tenant_token(self, client, tenant_a, tenant_b, user_a):
        # Forge the scenario: user_a's token but tenant_b's claim.
        from accounts.serializers import TenantTokenObtainPairSerializer
        from rest_framework.test import APIClient

        token = TenantTokenObtainPairSerializer.get_token(user_a)
        token["tenant_id"] = str(tenant_b.id)  # tampered claim
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        resp = c.get("/api/kb/knowledge-bases/")
        assert resp.status_code == 403

    def test_middleware_sets_thread_local(self, client_a, tenant_a):
        assert get_current_tenant() is None  # cleared outside requests
        client_a.get("/api/auth/me/")
        assert get_current_tenant() is None  # cleared after the request


@pytest.mark.django_db
class TestRowLevelSecurity:
    """Layer 2. Only meaningful on Postgres; skipped on SQLite."""

    requires_postgres = pytest.mark.skipif(
        connection.vendor != "postgresql", reason="RLS is a Postgres feature"
    )

    @requires_postgres
    def test_raw_sql_cannot_see_other_tenant_rows(self, tenant_a, tenant_b):
        set_current_tenant(tenant_a)
        KnowledgeBase.objects.create(tenant=tenant_a, name="Acme KB")
        set_current_tenant(tenant_b)
        KnowledgeBase.objects.create(tenant=tenant_b, name="Beta KB")

        # Act as tenant A at the SQL level, bypassing the ORM entirely.
        with connection.cursor() as cur:
            cur.execute("SET app.current_tenant = %s", [str(tenant_a.id)])
            cur.execute("SELECT name FROM kb_knowledgebase")
            names = {row[0] for row in cur.fetchall()}
            cur.execute("RESET app.current_tenant")
        assert names == {"Acme KB"}

    @requires_postgres
    def test_unset_tenant_sees_nothing(self, tenant_a):
        set_current_tenant(tenant_a)
        KnowledgeBase.objects.create(tenant=tenant_a, name="Acme KB")
        with connection.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM kb_knowledgebase")
            (count,) = cur.fetchone()
        assert count == 0  # fail closed when the setting is missing
