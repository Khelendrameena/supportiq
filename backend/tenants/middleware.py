"""Resolve the tenant for each request and arm both isolation layers.

Why the middleware authenticates the JWT itself: DRF's JWTAuthentication only
runs inside view dispatch, i.e. AFTER all Django middleware. The tenant must
be resolved (and the Postgres RLS session variable set) before any view code
touches the database, so this middleware validates the bearer token directly
with SimpleJWT. DRF re-validates the same token in the view — harmless.

Order in settings.MIDDLEWARE: after AuthenticationMiddleware (so session
auth, if ever used, is already applied) and before anything that queries.
"""
import logging

from django.http import JsonResponse
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken

from .models import Tenant, clear_current_tenant, set_current_tenant

logger = logging.getLogger("supportiq.tenants")


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.jwt_auth = JWTAuthentication()

    def __call__(self, request):
        clear_current_tenant()
        try:
            early_response = self._resolve_tenant(request)
            if early_response is not None:
                return early_response
            return self.get_response(request)
        finally:
            # clear_current_tenant() also RESETs the Postgres session
            # variable, so a pooled connection never carries one tenant's
            # identity into the next request.
            clear_current_tenant()

    def _resolve_tenant(self, request):
        """Returns a JsonResponse to short-circuit, or None to continue."""
        user, token = self._authenticate(request)
        if token == "invalid":
            return JsonResponse({"detail": "invalid or expired token"}, status=401)
        if token is None:
            # No bearer token: public endpoints (login/register/health) or
            # session auth. If a session user exists with a tenant, honor it.
            session_user = getattr(request, "user", None)
            if session_user and session_user.is_authenticated and getattr(session_user, "tenant_id", None):
                tenant = session_user.tenant
                set_current_tenant(tenant)
            return None

        tenant_id = token.get("tenant_id")
        if not tenant_id:
            return JsonResponse({"detail": "tenant_id claim missing in token"}, status=403)
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except (Tenant.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"detail": "unknown tenant"}, status=403)
        if getattr(user, "tenant_id", None) and str(user.tenant_id) != str(tenant.id):
            return JsonResponse({"detail": "user does not belong to tenant"}, status=403)

        request.user = user  # DRF will re-authenticate identically in the view
        set_current_tenant(tenant)
        logger.debug("tenant resolved", extra={"tenant_id": str(tenant.id)})
        return None

    def _authenticate(self, request):
        try:
            result = self.jwt_auth.authenticate(request)
        except (InvalidToken, AuthenticationFailed):
            return None, "invalid"  # sentinel: token present but bad
        if result is None:
            return None, None
        return result
