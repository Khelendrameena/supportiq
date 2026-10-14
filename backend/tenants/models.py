"""Tenant model + tenant-aware ORM helpers.

Isolation strategy (defense in depth):
  1. Application layer: every tenant-scoped model inherits TenantAwareModel,
     whose manager automatically filters by the current tenant resolved by
     TenantMiddleware. Forgetting a filter is therefore hard.
  2. Database layer (Postgres only): row-level security policies on all
     tenant tables, keyed off the `app.current_tenant` session setting that
     the middleware sets per request. Even a raw SQL slip can't cross tenants.

On SQLite (local dev/tests) only layer 1 is active; the RLS migration is a
no-op there.
"""
import threading
import uuid

from django.db import models

# Thread-local storage for the tenant resolved for the current request.
# (ASGI note: each request runs on its own thread/async context here; the
# middleware sets and clears this per request, see middleware.py.)
_thread_state = threading.local()


def set_current_tenant(tenant) -> None:
    _thread_state.tenant = tenant


def get_current_tenant():
    return getattr(_thread_state, "tenant", None)


def clear_current_tenant() -> None:
    _thread_state.tenant = None


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
