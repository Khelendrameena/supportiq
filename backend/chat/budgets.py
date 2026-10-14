"""Per-tenant monthly token budgets.

Estimates are charged BEFORE generation (fail fast instead of mid-stream)
using the provider's estimate_tokens(). Counters live in the cache backend;
on cache failure we fail closed (deny) because an unbounded LLM bill is the
worse failure mode — the opposite choice from rate limiting, and deliberate.
"""
from __future__ import annotations

import datetime
import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("supportiq.budgets")


class BudgetExceeded(Exception):
    pass


def _month_key(tenant_id) -> str:
    month = datetime.date.today().strftime("%Y-%m")
    return f"budget:{tenant_id}:{month}"


def check_and_charge(tenant_id, estimated_tokens: int) -> int:
    """Charge estimated tokens; returns the new monthly total. Raises if over."""
    key = _month_key(tenant_id)
    limit = settings.TOKEN_BUDGET_PER_TENANT
    try:
        # 35-day TTL comfortably covers any calendar month.
        total = cache.get(key)
        if total is None:
            cache.set(key, estimated_tokens, 60 * 60 * 24 * 35)
            total = estimated_tokens
        else:
            total = cache.incr(key, estimated_tokens)
    except Exception as exc:  # noqa: BLE001
        logger.error("budget counter unavailable — denying request", extra={"error": str(exc)})
        raise BudgetExceeded("token budget service unavailable") from exc
    if total > limit:
        raise BudgetExceeded(f"monthly token budget exceeded ({total} > {limit})")
    return total


def current_usage(tenant_id) -> int:
    try:
        return int(cache.get(_month_key(tenant_id)) or 0)
    except Exception:  # noqa: BLE001
        return 0
