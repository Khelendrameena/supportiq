"""The answer pipeline: retrieve -> fuse -> rerank -> guard -> generate.

This is the unit the eval harness exercises. Every stage is observable:
timings are recorded on the returned Answer so evals/benchmarks print real
numbers instead of invented ones.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from django.conf import settings
from opentelemetry import trace

from llm import get_embedding_provider, get_llm_provider

from .bm25 import bm25_search
from .rerank import Candidate, content_terms, get_reranker
from .rrf import reciprocal_rank_fusion
from .vector import vector_search

logger = logging.getLogger("supportiq.retrieval")
tracer = trace.get_tracer(__name__)

SYSTEM_PROMPT = (
    "You are a customer support agent. Answer ONLY from the provided context. "
    "Every factual claim must cite its source as [n] matching the context numbering. "
    "If the context does not contain the answer, say you don't have that information."
)


@dataclass
class RankedChunk:
    chunk_id: int
    document_id: int
    document_title: str
    ord: int
    text: str
    score: float


@dataclass
class Citation:
    index: int  # 1-based, matches the [n] markers in context/answer
    document_title: str
    chunk_ord: int
    score: float


@dataclass
class Answer:
    text: str
    citations: list[Citation] = field(default_factory=list)
    abstained: bool = False
    top_score: float = 0.0
    timings_ms: dict = field(default_factory=dict)


def _chunk_embedding(chunk, dim: int):
    if chunk.embedding is None:
        return None
    if settings.IS_POSTGRES:
        # pgvector returns numpy scalars (float32); cast to plain Python
        # floats so downstream scores stay JSON-serializable and hashable.
        return [float(x) for x in chunk.embedding]
    from kb.models import unpack_embedding

    return unpack_embedding(chunk.embedding, dim)


def retrieve(
    tenant_id, kb_id, question: str, top_k: int | None = None
) -> tuple[list[RankedChunk], dict]:
    """Hybrid retrieval: vector + BM25 -> RRF -> rerank.

    Returns (top_k ranked chunks, stage timings in ms).
    """
    top_k = top_k or settings.RETRIEVAL_TOP_K
    timings: dict[str, float] = {}
    embedder = get_embedding_provider()

    with tracer.start_as_current_span("embed.query") as span:
        t0 = time.perf_counter()
        query_vector = embedder.embed([question])[0]
        timings["embed_ms"] = (time.perf_counter() - t0) * 1000

    with tracer.start_as_current_span("retrieve.vector"):
        t0 = time.perf_counter()
        vec_hits = vector_search(tenant_id, kb_id, query_vector, top_k=50)
        timings["vector_ms"] = (time.perf_counter() - t0) * 1000

    with tracer.start_as_current_span("retrieve.bm25"):
        t0 = time.perf_counter()
        bm25_hits = bm25_search(tenant_id, kb_id, question, top_k=50)
        timings["bm25_ms"] = (time.perf_counter() - t0) * 1000

    fused = reciprocal_rank_fusion(
        [[cid for cid, _ in vec_hits], [cid for cid, _ in bm25_hits]]
    )
    candidate_ids = [cid for cid, _ in fused[:20]]
    if not candidate_ids:
        return [], timings

    from kb.models import Chunk

    chunks = {
        c.id: c
        for c in Chunk.all_objects.filter(id__in=candidate_ids).select_related("document")
    }
    # Preserve fusion order.
    ordered = [chunks[cid] for cid in candidate_ids if cid in chunks]

    dim = getattr(embedder, "dim", settings.EMBEDDING_DIM)
    candidates = [
        Candidate(chunk_id=c.id, text=c.text, embedding=_chunk_embedding(c, dim)) for c in ordered
    ]
    with tracer.start_as_current_span("retrieve.rerank"):
        t0 = time.perf_counter()
        reranked = get_reranker().rerank(question, query_vector, candidates)
        timings["rerank_ms"] = (time.perf_counter() - t0) * 1000

    by_id = {c.id: c for c in ordered}
    ranked = [
        RankedChunk(
            chunk_id=cid,
            document_id=by_id[cid].document_id,
            document_title=by_id[cid].document.title,
            ord=by_id[cid].ord,
            text=by_id[cid].text,
            score=score,
        )
        for cid, score in reranked[:top_k]
        if cid in by_id
    ]
    return ranked, timings


def build_prompt(question: str, ranked: list[RankedChunk]) -> tuple[str, str]:
    """Render the LLM prompt with numbered, citable context blocks."""
    blocks = []
    for i, r in enumerate(ranked, start=1):
        blocks.append(f"[{i}] {r.text}\n    (source: {r.document_title})")
    user = f"Question: {question}\n\nContext:\n" + "\n".join(blocks)
    return SYSTEM_PROMPT, user


def _has_sufficient_evidence(question: str, top: RankedChunk) -> bool:
    """Hallucination guard: is the top chunk really about the question?

    Two tiers:
      1. The rerank score must clear ABSTAIN_THRESHOLD (weak overall -> refuse).
      2. If the chunk shares NO content terms with the question, the match is
         embedding-only. Heuristic embeddings have no reliable synonym signal,
         so embedding-only evidence must clear the higher
         ABSTAIN_SEMANTIC_ONLY_THRESHOLD bar.
    """
    if top.score < settings.ABSTAIN_THRESHOLD:
        return False
    if not (content_terms(question) & content_terms(top.text)):
        return top.score >= settings.ABSTAIN_SEMANTIC_ONLY_THRESHOLD
    return True


def answer_question(tenant_id, kb_id, question: str) -> Answer:
    """Full pipeline: retrieve, abstain if weak, else generate a cited answer."""
    t0 = time.perf_counter()
    ranked, timings = retrieve(tenant_id, kb_id, question)

    top_score = ranked[0].score if ranked else 0.0
    if not ranked or not _has_sufficient_evidence(question, ranked[0]):
        # Hallucination guard: refuse rather than invent an answer.
        logger.info(
            "abstained: insufficient evidence",
            extra={"top_score": round(top_score, 3), "threshold": settings.ABSTAIN_THRESHOLD},
        )
        timings["total_ms"] = (time.perf_counter() - t0) * 1000
        return Answer(
            text="I don't have information about that in the knowledge base.",
            abstained=True,
            top_score=top_score,
            timings_ms=timings,
        )

    system, user = build_prompt(question, ranked)
    llm = get_llm_provider()
    with tracer.start_as_current_span("llm.generate", attributes={"llm.backend": llm.name}):
        t1 = time.perf_counter()
        text = llm.generate(system, user)
        timings["llm_ms"] = (time.perf_counter() - t1) * 1000

    citations = [
        Citation(index=i + 1, document_title=r.document_title, chunk_ord=r.ord, score=round(r.score, 3))
        for i, r in enumerate(ranked)
    ]
    timings["total_ms"] = (time.perf_counter() - t0) * 1000
    logger.info(
        "answer generated",
        extra={"top_score": round(top_score, 3), "citations": len(citations), "llm": llm.name},
    )
    return Answer(text=text, citations=citations, top_score=top_score, timings_ms=timings)
