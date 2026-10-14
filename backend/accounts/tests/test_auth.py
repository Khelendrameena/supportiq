"""Auth flow: register -> JWT with tenant_id claim -> me."""
import pytest


@pytest.mark.django_db
class TestAuth:
    def test_register_creates_tenant_and_returns_tokens(self, client):
        resp = client.post(
            "/api/auth/register/",
            {
                "tenant_name": "Gamma Inc",
                "tenant_slug": "gamma",
                "email": "g@gamma.example",
                "password": "password123",
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["tenant"]["slug"] == "gamma"
        assert body["access"] and body["refresh"]

    def test_register_duplicate_slug_rejected(self, client):
        payload = {
            "tenant_name": "Gamma Inc", "tenant_slug": "gamma",
            "email": "g@gamma.example", "password": "password123",
        }
        assert client.post("/api/auth/register/", payload, format="json").status_code == 201
        payload["email"] = "other@gamma.example"
        resp = client.post("/api/auth/register/", payload, format="json")
        assert resp.status_code == 400

    def test_login_token_carries_tenant_claim(self, client, user_a, tenant_a):
        resp = client.post(
            "/api/auth/token/",
            {"username": "alice@acme.example", "password": "password123"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        # Decode the access token WITHOUT verification to inspect claims.
        from rest_framework_simplejwt.tokens import AccessToken

        token = AccessToken(resp.json()["access"])
        assert token["tenant_id"] == str(tenant_a.id)

    def test_me_returns_tenant(self, client_a, tenant_a):
        resp = client_a.get("/api/auth/me/")
        assert resp.status_code == 200
        assert resp.json()["tenant"]["slug"] == tenant_a.slug

    def test_unauthenticated_me_is_401(self, client):
        assert client.get("/api/auth/me/").status_code == 401
