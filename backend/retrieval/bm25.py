"""Keyword search (BM25-style).

Postgres path: tsvector/ts_rank via parameterized raw SQL (english config).
SQLite path: a compact, real BM25 implementation in pure Python.

Both return [(chunk_id, score), ...] ordered best-first. Scores are only
compared within one backend (RRF fusion uses ranks, not scores).
"""
from __future__ import annotations

import math
import re
from collections import Counter

from django.conf import settings
from django.db import connection

_WORD = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def bm25_search(tenant_id, kb_id, query: str, top_k: int = 50) -> list[tuple[int, float]]:
    if settings.IS_POSTGRES:
        return _postgres_bm25(tenant_id, kb_id, query, top_k)
    return _python_bm25(tenant_id, kb_id, query, top_k)


def _postgres_bm25(tenant_id, kb_id, query: str, top_k: int) -> list[tuple[int, float]]:
    sql = """
        SELECT id,
               ts_rank(to_tsvector('english', text),
                       plainto_tsquery('english', %s)) AS rank
          FROM kb_chunk
         WHERE tenant_id = %s AND kb_id = %s
           AND to_tsvector('english', text) @@ plainto_tsquery('english', %s)
         ORDER BY rank DESC
         LIMIT %s
    """
    with connection.cursor() as cur:
        cur.execute(sql, [query, str(tenant_id), kb_id, query, top_k])
        return [(row[0], float(row[1])) for row in cur.fetchall()]


def _python_bm25(tenant_id, kb_id, query: str, top_k: int, k1: float = 1.5, b: float = 0.75):
    """Standard BM25 (Robertson & Zaragoza). Deterministic, no dependencies."""
    from kb.models import Chunk

    docs = list(
        Chunk.all_objects.filter(tenant_id=tenant_id, kb_id=kb_id).values_list("id", "text")
    )
    if not docs:
        return []
    tokenized = [(cid, tokenize(text)) for cid, text in docs]
    doc_count = len(tokenized)
    avg_len = sum(len(toks) for _, toks in tokenized) / doc_count
    # Document frequency per query term.
    q_terms = tokenize(query)
    df = Counter()
    for _, toks in tokenized:
        for term in set(toks) & set(q_terms):
            df[term] += 1
    scored = []
    for cid, toks in tokenized:
        tf = Counter(toks)
        length = len(toks) or 1
        score = 0.0
        for term in q_terms:
            if term not in tf:
                continue
            idf = math.log(1 + (doc_count - df[term] + 0.5) / (df[term] + 0.5))
            numer = tf[term] * (k1 + 1)
            denom = tf[term] + k1 * (1 - b + b * length / avg_len)
            score += idf * numer / denom
        if score > 0:
            scored.append((cid, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]
