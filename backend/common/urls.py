"""Liveness/readiness probes (used by docker-compose healthchecks)."""
from django.db import connection
from django.http import JsonResponse
from django.urls import path
from django.views import View


class HealthView(View):
    def get(self, request):
        checks = {"db": False}
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
            checks["db"] = True
        except Exception:  # noqa: BLE001 - health check must never raise
            pass
        status = 200 if all(checks.values()) else 503
        return JsonResponse({"status": "ok" if status == 200 else "degraded", **checks}, status=status)


urlpatterns = [path("", HealthView.as_view())]
