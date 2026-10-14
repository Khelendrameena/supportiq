"""Shared pytest fixtures for the whole repo (backend + evals)."""
import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.serializers import TenantTokenObtainPairSerializer
from kb.models import Document, KnowledgeBase
from kb.tasks import compute_content_hash, ingest_document
from tenants.models import Tenant, set_current_tenant

SAMPLE_DOC = """Acme Cloud Support Handbook

Refund policy: We offer a 30-day money-back guarantee on all paid plans.
To request a refund, email billing@acme.example with your invoice number.
Refunds are processed within 5 business days.

Password reset: Go to Settings, then Security, then click Reset Password.
You will receive an email with a reset link valid for 1 hour.

Support hours: Our support team is available Monday to Friday, 9am to 6pm IST.
Emergency support for enterprise plans is available 24/7.

Data export: You can export all your data from Settings, then Data, then Export.
Exports are delivered as a ZIP file within 24 hours.
"""


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def tenant_a(db):
    return Tenant.objects.create(name="Acme Corp", slug="acme")


@pytest.fixture
def tenant_b(db):
    return Tenant.objects.create(name="Beta LLC", slug="beta")


@pytest.fixture
def user_a(db, tenant_a):
    return get_user_model().objects.create_user(
        username="alice@acme.example", email="alice@acme.example",
        password="password123", tenant=tenant_a, is_tenant_admin=True,
    )


@pytest.fixture
def user_b(db, tenant_b):
    return get_user_model().objects.create_user(
        username="bob@beta.example", email="bob@beta.example",
        password="password123", tenant=tenant_b, is_tenant_admin=True,
    )


def _token_for(user):
    token = TenantTokenObtainPairSerializer.get_token(user)
    return str(token.access_token)


@pytest.fixture
def client_a(user_a):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(user_a)}")
    return client


@pytest.fixture
def client_b(user_b):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token_for(user_b)}")
    return client


@pytest.fixture
def kb_a(db, tenant_a):
    set_current_tenant(tenant_a)
    return KnowledgeBase.objects.create(
        tenant=tenant_a, name="Support KB", description="Acme support docs"
    )


def ingest_text(tenant, kb, title, text, filename="doc.txt"):
    """Synchronously ingest a text document (Celery eager in tests)."""
    from django.core.files.base import ContentFile

    set_current_tenant(tenant)
    raw = text.encode()
    doc = Document.all_objects.create(
        tenant=tenant, kb=kb, title=title,
        file=ContentFile(raw, name=filename),
        content_hash=compute_content_hash(raw),
    )
    result = ingest_document(doc.id)  # runs inline; eager mode anyway
    doc.refresh_from_db()
    assert doc.status == Document.Status.READY, doc.error
    return doc, result


@pytest.fixture
def kb_a_ingested(tenant_a, kb_a):
    ingest_text(tenant_a, kb_a, "Support Handbook", SAMPLE_DOC)
    return kb_a
