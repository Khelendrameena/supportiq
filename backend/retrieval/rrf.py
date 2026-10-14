"""Reciprocal Rank Fusion (Cormack et al., SIGIR 2009).

Fuses ranked lists from different retrievers (vector, BM25) using only their
RANKS — never their raw scores, which live on incomparable scales. This is
the standard, principled way to do hybrid search fusion.
"""
from __future__ import annotations


def reciprocal_rank_fusion(ranked_lists: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """Fuse id-ranked lists -> [(chunk_id, rrf_score)] ordered best-first.

    score(d) = sum over lists of 1 / (k + rank(d)), rank starting at 1.
    The constant k=60 dampens the influence of very high ranks (per the paper).
    """
    fused: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda item: item[1], reverse=True)
