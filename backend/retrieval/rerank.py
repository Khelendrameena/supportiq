"""Reranking: score (query, chunk) pairs precisely after cheap retrieval.

Interface + two backends:
  RERANKER_BACKEND=heuristic       (default) deterministic, no dependencies
  RERANKER_BACKEND=cross-encoder   real cross-encoder via sentence-transformers

Scores are normalized to [0, 1]; the pipeline abstains below ABSTAIN_THRESHOLD.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence

from django.conf import settings

from .bm25 import tokenize
from .vector import cosine_similarity

# Common English stopwords: excluded from the overlap signal so that
# "what is the capital of X" doesn't match chunks just for "what/is/the".
STOPWORDS = frozenset(
    "a an the and or but if then else when at by for with about into through "
    "during before after above below to from up down in out on off over under "
    "again further once here there what which who whom this that these those "
    "am is are was were be been being have has had having do does did doing "
    "would should could ought i me my we our you your he him his she her it "
    "its they them their of in as at to".split()
)


def content_terms(text: str) -> set[str]:
    return {t for t in tokenize(text) if t not in STOPWORDS}


@dataclass
class Candidate:
    chunk_id: int
    text: str
    embedding: list[float] | None = None


class Reranker(ABC):
    name = "base"

    @abstractmethod
    def rerank(self, query: str, query_embedding: list[float], candidates: Sequence[Candidate]) -> list[tuple[int, float]]:
        """Return [(chunk_id, score in [0,1]), ...] ordered best-first."""


class HeuristicReranker(Reranker):
    """Deterministic fallback: cosine similarity blended with term overlap.

    Not as good as a cross-encoder, but honest, fast, dependency-free, and
    good enough that the eval harness measures real differences.
    """

    name = "heuristic"
    weight_cosine = 0.6
    weight_overlap = 0.4

    def rerank(self, query, query_embedding, candidates):
        q_terms = content_terms(query)
        scored = []
        for cand in candidates:
            cos = cosine_similarity(query_embedding, cand.embedding) if cand.embedding else 0.0
            # Map cosine [-1, 1] -> [0, 1].
            cos_n = max(0.0, min(1.0, (cos + 1.0) / 2.0))
            overlap = len(q_terms & content_terms(cand.text)) / max(1, len(q_terms))
            score = self.weight_cosine * cos_n + self.weight_overlap * overlap
            scored.append((cand.chunk_id, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored


class CrossEncoderReranker(Reranker):
    """Real cross-encoder reranker (ms-marco style). Needs sentence-transformers."""

    name = "cross-encoder"

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed. pip install sentence-transformers "
                "or set RERANKER_BACKEND=heuristic."
            ) from exc
        self._model = CrossEncoder(model_name)

    def rerank(self, query, query_embedding, candidates):
        import math

        pairs = [(query, c.text) for c in candidates]
        logits = self._model.predict(pairs)
        # Sigmoid to [0, 1].
        scored = [
            (c.chunk_id, 1.0 / (1.0 + math.exp(-float(l))))
            for c, l in zip(candidates, logits)
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored


def get_reranker() -> Reranker:
    if settings.RERANKER_BACKEND.lower() == "cross-encoder":
        return CrossEncoderReranker()
    return HeuristicReranker()
