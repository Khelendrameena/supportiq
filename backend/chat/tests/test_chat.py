"""Chat API: SSE streaming, semantic cache, rate limits, budgets, resilience."""
import json

import pytest
from django.test import override_settings
from tenants.models import set_current_tenant


def read_sse(response):
    """Parse a StreamingHttpResponse into a list of event dicts."""
    events = []
    for raw in response.streaming_content:
        text = raw.decode() if isinstance(raw, bytes) else raw
        for line in text.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


@pytest.mark.django_db
class TestChat:
    def test_ask_streams_tokens_then_done(self, client_a, kb_a_ingested):
        resp = client_a.post(
            "/api/chat/ask/",
            {"kb_id": kb_a_ingested.id, "question": "What is the refund policy?"},
            format="json",
        )
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/event-stream"
        events = read_sse(resp)
        tokens = [e for e in events if e["type"] == "token"]
        done = [e for e in events if e["type"] == "done"]
        assert tokens and len(done) == 1
        final = done[0]
        assert final["cache"] == "MISS"
        assert not final["abstained"]
        assert final["citations"]
        assert "".join(t["text"] for t in tokens) == final["answer"]

    def test_second_ask_is_cache_hit(self, client_a, kb_a_ingested):
        payload = {"kb_id": kb_a_ingested.id, "question": "What is the refund policy?"}
        first = read_sse(client_a.post("/api/chat/ask/", payload, format="json"))
        second = read_sse(client_a.post("/api/chat/ask/", payload, format="json"))
        assert [e for e in first if e["type"] == "done"][0]["cache"] == "MISS"
        done2 = [e for e in second if e["type"] == "done"][0]
        assert done2["cache"] == "HIT"
        assert done2["answer"] == [e for e in first if e["type"] == "done"][0]["answer"]

    def test_off_topic_question_abstains(self, client_a, kb_a_ingested):
        events = read_sse(
            client_a.post(
                "/api/chat/ask/",
                {"kb_id": kb_a_ingested.id, "question": "What is the capital of Assyria?"},
                format="json",
            )
        )
        done = [e for e in events if e["type"] == "done"][0]
        assert done["abstained"] is True
        assert done["citations"] == []

    def test_conversation_history_persisted(self, client_a, kb_a_ingested, tenant_a):
        from chat.models import Message

        read_sse(
            client_a.post(
                "/api/chat/ask/",
                {"kb_id": kb_a_ingested.id, "question": "What is the refund policy?"},
                format="json",
            )
        )
        set_current_tenant(tenant_a)  # middleware clears thread-local after the request
        roles = list(Message.objects.values_list("role", flat=True))
        assert roles == ["user", "assistant"]
        assistant_msg = Message.objects.get(role="assistant")
        assert assistant_msg.citations  # citations persisted, not just streamed

    def test_conversations_list(self, client_a, kb_a_ingested):
        read_sse(
            client_a.post(
                "/api/chat/ask/",
                {"kb_id": kb_a_ingested.id, "question": "What is the refund policy?"},
                format="json",
            )
        )
        resp = client_a.get("/api/chat/conversations/")
        assert resp.status_code == 200
        convos = resp.json()["results"]
        assert len(convos) == 1
        assert len(convos[0]["messages"]) == 2

    @override_settings(RATE_LIMIT_PER_USER=1, RATE_LIMIT_PER_TENANT=1000)
    def test_per_user_rate_limit(self, client_a, kb_a_ingested):
        payload = {"kb_id": kb_a_ingested.id, "question": "What is the refund policy?"}
        read_sse(client_a.post("/api/chat/ask/", payload, format="json"))
        events = read_sse(client_a.post("/api/chat/ask/", payload, format="json"))
        errors = [e for e in events if e["type"] == "error"]
        assert errors and errors[0]["code"] == "rate_limited"

    @override_settings(TOKEN_BUDGET_PER_TENANT=1)
    def test_token_budget_exceeded(self, client_a, kb_a_ingested):
        events = read_sse(
            client_a.post(
                "/api/chat/ask/",
                {"kb_id": kb_a_ingested.id, "question": "What is the refund policy?"},
                format="json",
            )
        )
        errors = [e for e in events if e["type"] == "error"]
        assert errors and errors[0]["code"] == "budget_exceeded"

    def test_budget_endpoint(self, client_a):
        resp = client_a.get("/api/chat/budget/")
        assert resp.status_code == 200
        assert resp.json()["limit"] > 0

    def test_chat_survives_cache_outage(self, client_a, kb_a_ingested, monkeypatch):
        """RUNBOOK drill: Redis down -> no 500s, ever.

        The token-budget counter is deliberately fail-CLOSED when the cache is
        unreachable (an unbounded LLM bill is the worse failure mode), so chat
        answers degrade to a clean, structured SSE error event — not a 500,
        not a hang. Rate limiting degrades fail-open (logged loudly).
        """
        from django.core import cache as cache_module

        def boom(*args, **kwargs):
            raise ConnectionError("redis is down")

        monkeypatch.setattr(cache_module.cache, "get", boom)
        monkeypatch.setattr(cache_module.cache, "set", boom)
        monkeypatch.setattr(cache_module.cache, "incr", boom)
        resp = client_a.post(
            "/api/chat/ask/",
            {"kb_id": kb_a_ingested.id, "question": "What is the refund policy?"},
            format="json",
        )
        assert resp.status_code == 200  # the HTTP layer never 500s
        events = read_sse(resp)
        errors = [e for e in events if e["type"] == "error"]
        assert errors and errors[0]["code"] == "budget_exceeded"
        assert "detail" in errors[0]  # human-readable reason for the UI
