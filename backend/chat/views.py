"""Chat API: SSE streaming answers + conversation history."""
import json
import logging

from django.conf import settings
from django.http import StreamingHttpResponse
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from kb.models import KnowledgeBase
from tenants.models import clear_current_tenant, get_current_tenant, set_current_tenant

from . import budgets
from .models import Conversation, Message
from .ratelimit import RateLimitExceeded
from .services import stream_chat_events

logger = logging.getLogger("supportiq.chat")


class AskSerializer(serializers.Serializer):
    kb_id = serializers.IntegerField()
    question = serializers.CharField(max_length=2000)
    conversation_id = serializers.IntegerField(required=False, allow_null=True)


class AskView(APIView):
    """POST /api/chat/ask -> text/event-stream of tokens + final payload."""

    def post(self, request):
        serializer = AskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = get_current_tenant()
        try:
            kb = KnowledgeBase.objects.get(id=serializer.validated_data["kb_id"])
        except KnowledgeBase.DoesNotExist:
            return Response({"detail": "knowledge base not found"}, status=status.HTTP_404_NOT_FOUND)

        question = serializer.validated_data["question"]
        conversation_id = serializer.validated_data.get("conversation_id")

        def event_stream():
            # This generator runs LAZILY -- the middleware has already
            # returned (and cleared the tenant + RESET the RLS session
            # variable) by the time the first chunk is consumed. Re-arm the
            # tenant for this unit of work so ORM scoping and the Postgres
            # RLS policy both see the right identity, then clear it when
            # the stream ends.
            set_current_tenant(tenant)
            try:
                for event in stream_chat_events(tenant, request.user, kb, question, conversation_id):
                    yield f"data: {json.dumps(event)}\n\n"
            except RateLimitExceeded as exc:
                yield f"data: {json.dumps({'type': 'error', 'code': 'rate_limited', 'retry_after': exc.retry_after})}\n\n"
            except budgets.BudgetExceeded as exc:
                yield f"data: {json.dumps({'type': 'error', 'code': 'budget_exceeded', 'detail': str(exc)})}\n\n"
            finally:
                clear_current_tenant()

        response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # don't let nginx buffer the stream
        return response


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "role", "text", "citations", "abstained", "cache_hit", "latency_ms", "created_at"]


class ConversationSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)
    kb_name = serializers.CharField(source="kb.name", read_only=True)

    class Meta:
        model = Conversation
        fields = ["id", "kb", "kb_name", "title", "messages", "created_at"]


class ConversationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ConversationSerializer

    def get_queryset(self):
        # Per-request: see KnowledgeBaseViewSet for why this can't be a
        # class-level queryset with the tenant-aware manager.
        return (
            Conversation.objects.all().order_by("-created_at").prefetch_related("messages", "kb")
        )


class BudgetView(APIView):
    """GET /api/chat/budget/ -> this tenant's current month token usage."""

    def get(self, request):
        tenant = get_current_tenant()
        return Response(
            {
                "used": budgets.current_usage(tenant.id),
                "limit": settings.TOKEN_BUDGET_PER_TENANT,
            }
        )
