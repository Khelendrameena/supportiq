"""Vector similarity search over chunk embeddings.

Postgres path: pgvector HNSW index, cosine distance via ORM annotation.
SQLite path (local dev/tests): brute-force cosine in Python over the packed
blob column. Same semantics, slower — documented in README trade-offs.
"""
from __future__ import annotations

import heapq
import math

from django.conf import settings


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def vector_search(tenant_id, kb_id, query_vector: list[float], top_k: int = 50) -> list[tuple[int, float]]:
    """Return [(chunk_id, cosine_similarity), ...] ordered best-first."""
    from kb.models import Chunk, unpack_embedding

    if settings.IS_POSTGRES:
        from pgvector.django import CosineDistance

        rows = (
            Chunk.all_objects.filter(tenant_id=tenant_id, kb_id=kb_id)
            .exclude(embedding__isnull=True)
            .annotate(distance=CosineDistance("embedding", query_vector))
            .order_by("distance")
            .values_list("id", "distance")[:top_k]
        )
        # pgvector <=> is cosine DISTANCE; convert to similarity for a
        # consistent [−1, 1] scale across backends.
        return [(cid, 1.0 - float(dist)) for cid, dist in rows]

    dim = settings.EMBEDDING_DIM
    scored = []
    for cid, blob in (
        Chunk.all_objects.filter(tenant_id=tenant_id, kb_id=kb_id)
        .exclude(embedding__isnull=True)
        .values_list("id", "embedding")
    ):
        sim = cosine_similarity(query_vector, unpack_embedding(blob, dim))
        scored.append((sim, cid))
    top = heapq.nlargest(top_k, scored)
    return [(cid, sim) for sim, cid in top]
