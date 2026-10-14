"""Chat models: conversations and messages (tenant-scoped)."""
from django.conf import settings
from django.db import models
from tenants.models import TenantAwareModel


class Conversation(TenantAwareModel):
    kb = models.ForeignKey("kb.KnowledgeBase", on_delete=models.CASCADE, related_name="conversations")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations")
    title = models.CharField(max_length=300, default="")
    created_at = models.DateTimeField(auto_now_add=True)


class Message(TenantAwareModel):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=Role.choices)
    text = models.TextField()
    # Stored as JSON: [{"index": 1, "document_title": ..., "chunk_ord": ..., "score": ...}]
    citations = models.JSONField(default=list, blank=True)
    tokens_used = models.IntegerField(default=0)
    latency_ms = models.FloatField(default=0.0)
    cache_hit = models.BooleanField(default=False)
    abstained = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
