"""Root URL configuration."""
from django.contrib import admin  # noqa: F401  (kept importable, not wired)
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("api/auth/", include("accounts.urls")),
    path("api/kb/", include("kb.urls")),
    path("api/chat/", include("chat.urls")),
    path("api/health/", include("common.urls")),
]
