"""Tenant model + tenant-aware ORM helpers.

Isolation strategy (defense in depth):
  1. Application layer: every tenant-scoped model inherits TenantAwareModel,
     whose manager automatically filters by the current tenant resolved by
     TenantMiddleware. Forgetting a filter is therefore hard.
  2. Database layer (Postgres only): row-level security policies on all
     tenant tables, keyed off the `app.current_tenant` session setting that
     `set_current_tenant()` mirrors from thread-local (RESET on clear, so
     pooled connections can't leak identity). Even a raw SQL slip can't
     cross tenants.

On SQLite (local dev/tests) only layer 1 is active; the RLS migration is a
no-op there.
"""
import logging
import threading
import uuid

from django.db import connection, models

logger = logging.getLogger("supportiq.tenants")

# Thread-local storage for the tenant resolved for the current request.
# (ASGI note: each request runs on its own thread/async context here; the
# middleware sets and clears this per request, see middleware.py.)
_thread_state = threading.local()


def _arm_rls_session(tenant) -> None:
    """Mirror the thread-local tenant into the Postgres session variable
    that the RLS policies read.

    One function owns both isolation layers, so ORM-level code (tests,
    Celery tasks, management commands) can't arm the ORM layer and forget
    the database layer the way it could when only the middleware issued
    the SET. No-op on SQLite, where the RLS migration is a no-op too."""
    if connection.vendor != "postgresql":
        return
    try:
        with connection.cursor() as cur:
            if tenant is None:
                # RESET so a pooled/reused connection never carries one
                # tenant's identity into the next unit of work.
                cur.execute("RESET app.current_tenant")
            else:
                cur.execute("SET app.current_tenant = %s", [str(tenant.id)])
    except RuntimeError:
        # Pure unit tests (no django_db mark) are blocked from touching the
        # database at all -- and without DB access the RLS session variable
        # is meaningless anyway. In every real runtime (requests, workers,
        # management commands) DB access is allowed, so the SET happens.
        logger.debug("skipping RLS session arming: no database access")


def set_current_tenant(tenant) -> None:
    _thread_state.tenant = tenant
    _arm_rls_session(tenant)


def get_current_tenant():
    return getattr(_thread_state, "tenant", None)


def clear_current_tenant() -> None:
    _thread_state.tenant = None
    _arm_rls_session(None)


class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name} ({self.slug})"


class TenantAwareManager(models.Manager):
    """Manager that scopes every queryset to the current tenant."""

    def get_queryset(self):
        qs = super().get_queryset()
        tenant = get_current_tenant()
        if tenant is None:
            # Fail closed: without a resolved tenant, return nothing rather
            # than leaking rows. Superuser tooling must set a tenant explicitly.
            return qs.none()
        return qs.filter(tenant=tenant)


class TenantAwareModel(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="+")

    objects = TenantAwareManager()
    # Unscoped access for migrations/admin tooling. Name is explicit so nobody
    # reaches for it by accident in request code.
    all_objects = models.Manager()

    class Meta:
        abstract = True
