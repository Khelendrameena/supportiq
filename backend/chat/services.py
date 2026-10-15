"""Chat orchestration: rate limits -> cache -> retrieval -> guardrails -> LLM.

stream_chat_events() is a generator yielding event dicts; the view formats
them as SSE. Persistence (Conversation/Message rows) happens here so both the
API and the eval harness share one code path.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict

from opentelemetry import trace

from llm import get_llm_provider
from retrieval import Citation, build_prompt, retrieve
from retrieval.pipeline import _has_sufficient_evidence

from . import budgets
from .cache import get_cached_answer, set_cached_answer
from .models import Conversation, Message
from .ratelimit import check_chat_limits

logger = logging.getLogger("supportiq.chat")
tracer = trace.get_tracer(__name__)


def stream_chat_events(tenant, user, kb, question: str, conversation_id=None):
    """Yield {"type": "token", "text": ...} then a final {"type": "done", ...}."""
    t_start = time.perf_counter()
    check_chat_limits(user.id, tenant.id)

    conversation = _get_conversation(tenant, user, kb, conversation_id)
    _save_message(conversation, tenant, Message.Role.USER, question)

    cached = get_cached_answer(tenant.id, kb.id, question)
    if cached is not None:
        text = cached["text"]
        yield {"type": "token", "text": text}  # one chunk: already complete
        citations = cached.get("citations", [])
        result = _finish(
            conversation, tenant, text, citations, abstained=False,
            cache_hit=True, tokens=0, latency_ms=(time.perf_counter() - t_start) * 1000,
        )
        logger.info("chat cache HIT", extra={"latency_ms": round(result["latency_ms"], 1)})
        yield {"type": "done", **result, "cache": "HIT"}
        return

    ranked, timings = retrieve(tenant.id, kb.id, question)
    top_score = ranked[0].score if ranked else 0.0

    if not ranked or not _has_sufficient_evidence(question, ranked[0]):
        text = "I don't have information about that in the knowledge base."
        yield {"type": "token", "text": text}
        result = _finish(
            conversation, tenant, text, [], abstained=True,
            cache_hit=False, tokens=0, latency_ms=(time.perf_counter() - t_start) * 1000,
        )
        logger.info("chat abstained", extra={"top_score": round(top_score, 3)})
        yield {"type": "done", **result, "cache": "MISS"}
        return

    system, user_prompt = build_prompt(question, ranked)
    llm = get_llm_provider()
    # Budget check BEFORE streaming: estimate prompt + max completion.
    estimated = llm.estimate_tokens(system + user_prompt) + 512
    budgets.check_and_charge(tenant.id, estimated)

    pieces = []
    with tracer.start_as_current_span("llm.stream", attributes={"llm.backend": llm.name}):
        for piece in llm.stream(system, user_prompt):
            pieces.append(piece)
            yield {"type": "token", "text": piece}
    text = "".join(pieces)
    tokens_used = llm.estimate_tokens(text)

    citations = [asdict(Citation(index=i + 1, document_title=r.document_title,
                                 chunk_ord=r.ord, score=float(round(r.score, 3))))
                 for i, r in enumerate(ranked)]
    set_cached_answer(tenant.id, kb.id, question, {"text": text, "citations": citations})
    result = _finish(
        conversation, tenant, text, citations, abstained=False,
        cache_hit=False, tokens=tokens_used,
        latency_ms=(time.perf_counter() - t_start) * 1000,
    )
    logger.info("chat cache MISS", extra={**{k: round(v, 1) for k, v in timings.items()},
                                         "latency_ms": round(result["latency_ms"], 1)})
    yield {"type": "done", **result, "cache": "MISS"}


def _get_conversation(tenant, user, kb, conversation_id):
    if conversation_id:
        return Conversation.objects.get(id=conversation_id, kb=kb)
    title = (kb.name + " chat")
    return Conversation.objects.create(tenant=tenant, kb=kb, user=user, title=title[:300])


def _save_message(conversation, tenant, role, text, **kwargs):
    return Message.objects.create(
        tenant=tenant, conversation=conversation, role=role, text=text, **kwargs
    )


def _finish(conversation, tenant, text, citations, abstained, cache_hit, tokens, latency_ms):
    msg = _save_message(
        conversation, tenant, Message.Role.ASSISTANT, text,
        citations=citations, abstained=abstained, cache_hit=cache_hit,
        tokens_used=tokens, latency_ms=latency_ms,
    )
    return {
        "conversation_id": conversation.id,
        "message_id": msg.id,
        "answer": text,
        "citations": citations,
        "abstained": abstained,
        "latency_ms": round(latency_ms, 1),
    }
