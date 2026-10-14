"""Semantic (exact-match on normalized question) answer cache.

Key insight for the demo: repeated questions skip retrieval + LLM entirely.
Latency with/without cache is measured and logged — the benchmark command
prints real numbers (see chat/management/commands/benchmark_cache.py).

Resilience: every function swallows cache-backend errors. If Redis is down,
the chat path degrades to "no cache" instead of 500ing. This is the behavior
the RUNBOOK incident drill tests.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re

from django.core.cache import cache

logger = logging.getLogger("supportiq.cache")

CACHE_TTL_SECONDS = 60 * 60  # 1 hour


def normalize_question(question: str) -> str:
    q = question.strip().lower()
    q = re.sub(r"\s+", " ", q)
    return q.rstrip("?.!")


def _tenant_cache_version(tenant_id) -> str:
    """Per-tenant version counter; bumping it invalidates that tenant's cache."""
    try:
        return str(cache.get(f"answer-version:{tenant_id}", "v1"))
    except Exception:  # noqa: BLE001
        return "v1"


def cache_key(tenant_id, kb_id, question: str) -> str:
    version = _tenant_cache_version(tenant_id)
    digest = hashlib.sha256(
        f"{version}:{tenant_id}:{kb_id}:{normalize_question(question)}".encode()
    ).hexdigest()
    return f"answer:{digest}"


def get_cached_answer(tenant_id, kb_id, question: str) -> dict | None:
    try:
        raw = cache.get(cache_key(tenant_id, kb_id, question))
    except Exception as exc:  # noqa: BLE001 - cache must never break chat
        logger.warning("cache read failed (degraded, continuing)", extra={"error": str(exc)})
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def set_cached_answer(tenant_id, kb_id, question: str, payload: dict) -> None:
    try:
        cache.set(cache_key(tenant_id, kb_id, question), json.dumps(payload), CACHE_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 - cache must never break chat
        logger.warning("cache write failed (degraded, continuing)", extra={"error": str(exc)})


def invalidate_tenant_cache(tenant_id) -> None:
    """Invalidate a tenant's cached answers (call after KB ingestion).

    Bumps the per-tenant version so old keys simply stop matching. Old keys
    expire naturally via TTL — no expensive key scan needed.
    """
    try:
        current = cache.get(f"answer-version:{tenant_id}", "v1")
        bumped = f"v{int(current[1:]) + 1}" if current.startswith("v") and current[1:].isdigit() else "v2"
        cache.set(f"answer-version:{tenant_id}", bumped, None)
        logger.info("tenant cache invalidated", extra={"tenant_id": str(tenant_id)})
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache invalidation failed", extra={"error": str(exc)})
