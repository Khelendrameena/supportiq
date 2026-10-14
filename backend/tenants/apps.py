"""Tenants app config — also the hook that boots OpenTelemetry once."""
from django.apps import AppConfig


class TenantsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tenants"

    def ready(self):
        from common.otel import configure_tracing

        configure_tracing()
