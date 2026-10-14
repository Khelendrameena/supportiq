from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AskView, BudgetView, ConversationViewSet

router = DefaultRouter()
router.register("conversations", ConversationViewSet, basename="conversation")

urlpatterns = [
    path("ask/", AskView.as_view(), name="ask"),
    path("budget/", BudgetView.as_view(), name="budget"),
    path("", include(router.urls)),
]
