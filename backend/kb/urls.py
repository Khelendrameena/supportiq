from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import DocumentViewSet, KnowledgeBaseViewSet

router = DefaultRouter()
router.register("knowledge-bases", KnowledgeBaseViewSet, basename="kb")
router.register("documents", DocumentViewSet, basename="document")

urlpatterns = [path("", include(router.urls))]
