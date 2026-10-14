"""Eval scorers: faithfulness and answer relevance.

Both are real, deterministic measurements over the pipeline's actual output:

faithfulness: for each sentence in the answer, find the cited chunk with the
    highest word-overlap ratio (|intersection| / |sentence words|). A sentence
    counts as supported when that ratio >= 0.5. faithfulness =
    supported_sentences / total_sentences. Abstained answers score 1.0 iff
    abstention was expected, else 0.0.

answer_relevance: cosine similarity between the question embedding and the
    answer embedding (same embedder the pipeline uses). In [-1, 1]; higher is
    more on-topic.

keyword_recall: fraction of the golden `must_contain` keywords present in the
    answer (case-insensitive). A coarse correctness check.
"""
from __future__ import annotations

import re

from retrieval.vector import cosine_similarity

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def faithfulness(answer_text: str, cited_chunk_texts: list[str], abstain_expected: bool,
                 abstained: bool) -> float:
    if abstained:
        return 1.0 if abstain_expected else 0.0
    if abstain_expected:
        return 0.0  # should have abstained but didn't
    sentences = [s for s in _SENTENCE_SPLIT.split(answer_text.strip()) if s.strip()]
    if not sentences:
        return 0.0
    chunk_words = [_words(c) for c in cited_chunk_texts]
    supported = 0
    for sentence in sentences:
        s_words = _words(sentence)
        if not s_words:
            continue
        best = max((len(s_words & cw) / len(s_words) for cw in chunk_words), default=0.0)
        if best >= 0.5:
            supported += 1
    return supported / len(sentences)


def answer_relevance(question: str, answer_text: str, embedder) -> float:
    q_vec, a_vec = embedder.embed([question, answer_text])
    return cosine_similarity(q_vec, a_vec)


def keyword_recall(answer_text: str, must_contain: list[str]) -> float:
    if not must_contain:
        return 1.0
    lowered = answer_text.lower()
    hits = sum(1 for kw in must_contain if kw.lower() in lowered)
    return hits / len(must_contain)
