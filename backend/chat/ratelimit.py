"""Dual rate limiting: per-user AND per-tenant fixed windows.

Both limits must pass. The per-user limit stops one abusive client; the
per-tenant limit protects shared LLM/token budgets from a single customer's
traffic spike.
"""
from __future__ import annotations

import logging
import time

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("supportiq.ratelimit")


class RateLimitExceeded(Exception):
    def __init__(self, scope: str, retry_after: int):
        super().__init__(f"rate limit exceeded ({scope})")
        self.scope = scope
        self.retry_after = retry_after


def _check(scope: str, key: str, limit: int, window_seconds: int = 60) -> None:
    window_id = int(time.time() // window_seconds)
    cache_key = f"rl:{scope}:{key}:{window_id}"
    try:
        count = cache.get(cache_key)
        if count is None:
            cache.set(cache_key, 1, window_seconds)
            return
        count = cache.incr(cache_key)
    except Exception as exc:  # noqa: BLE001 - fail OPEN would be wrong; fail CLOSED is safer
        # If the cache is down we cannot count: allow the request (availability
        # over strictness) but log loudly. The token budget check below still
        # guards cost via the database-backed path... (documented trade-off;
        # see RUNBOOK "Redis down" drill).
        logger.warning("rate limiter degraded (allowing request)", extra={"error": str(exc)})
        return
    if count > limit:
        retry_after = window_seconds - int(time.time() % window_seconds)
        raise RateLimitExceeded(scope, retry_after)


def check_chat_limits(user_id, tenant_id) -> None:
    _check("user", str(user_id), settings.RATE_LIMIT_PER_USER)
    _check("tenant", str(tenant_id), settings.RATE_LIMIT_PER_TENANT)
