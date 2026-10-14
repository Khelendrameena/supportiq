"""Custom user: email login, belongs to exactly one tenant."""
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    # A user belongs to one tenant. Null only for the (optional) platform
    # superuser used for ops; every API user has a tenant.
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="users"
    )
    is_tenant_admin = models.BooleanField(default=False)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.username}@{self.tenant.slug if self.tenant else '-'}"
