"""Deterministic local providers. No network, no keys, reproducible.

FakeLLM is deliberately *not* a chatbot: it answers ONLY from the context
chunks it is given, citing them as [1], [2], ... This mirrors the retrieval
pipeline's contract (cited, grounded answers) and makes evals deterministic.
If the pipeline abstains, FakeLLM is never called.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Iterator, Sequence

from .base import EmbeddingProvider, LLMProvider

# Split on sentence-ending punctuation FOLLOWED BY WHITESPACE, so that
# "billing@acme.example" (no space after the dot) is never torn apart.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]


class DeterministicEmbeddings(EmbeddingProvider):
    """Hash-based random-projection embeddings.

    Each token hashes into buckets; the vector is L2-normalized. Similar
    texts share tokens -> similar vectors. Deterministic across runs
    (no Python hash randomization: uses sha256 explicitly).
    """

    name = "deterministic"

    def __init__(self, dim: int = 384):
        self.dim = dim

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if t]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vec = [0.0] * self.dim
            for token in self._tokens(text):
                # Two independent bucket indices per token reduce collisions.
                h = int(hashlib.sha256(token.encode()).hexdigest(), 16)
                vec[h % self.dim] += 1.0
                vec[(h >> 64) % self.dim] += 0.5
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


class FakeLLM(LLMProvider):
    """Builds a cited answer extractively from the provided context.

    The pipeline passes context as:
        [1] <chunk text>   (source: <doc title>)
        [2] <chunk text>   ...
    FakeLLM picks the sentences most overlapping the question and returns
    them with their citation markers. Streaming yields word-by-word.
    """

    name = "fake"

    def generate(self, system: str, user: str, *, max_tokens: int = 512) -> str:
        return self._answer(user)

    def stream(self, system: str, user: str, *, max_tokens: int = 512) -> Iterator[str]:
        for word in self._answer(user).split(" "):
            yield word + " "

    def estimate_tokens(self, text: str) -> int:
        # ~4 chars per token is the standard rough estimate.
        return max(1, len(text) // 4)

    # -- internals ------------------------------------------------------
    def _answer(self, user_prompt: str) -> str:
        question, sources = self._split_prompt(user_prompt)
        if not sources:
            return "I don't have information about that in the knowledge base."
        scored = []
        q_words = set(DeterministicEmbeddings._tokens(question))
        for idx, text in sources:
            s_words = set(DeterministicEmbeddings._tokens(text))
            overlap = len(q_words & s_words)
            if overlap:
                scored.append((overlap, idx, text))
        if not scored:
            # Question words don't appear in any chunk: cite the top chunk.
            idx, text = sources[0]
            first = _sentences(text)[0] if _sentences(text) else text[:200]
            return f"Based on the knowledge base [{idx}]: {first}."
        scored.sort(reverse=True)
        # Take the best sentence from each of the top-2 chunks.
        parts = []
        for _, idx, text in scored[:2]:
            best = max(
                _sentences(text),
                key=lambda s: len(q_words & set(DeterministicEmbeddings._tokens(s))),
                default="",
            )
            if best:
                parts.append(f"{best} [{idx}]")
        return " ".join(parts) if parts else f"See the knowledge base [{scored[0][1]}]."

    @staticmethod
    def _split_prompt(user_prompt: str):
        """Split 'Question: ...\\n\\nContext:\\n[1] ...' into (question, [(idx, text)])."""
        question, _, context = user_prompt.partition("Context:")
        question = question.replace("Question:", "").strip()
        sources = []
        for line in context.splitlines():
            line = line.strip()
            if line.startswith("["):
                end = line.find("]")
                if end > 1:
                    try:
                        idx = int(line[1:end])
                    except ValueError:
                        continue
                    sources.append((idx, line[end + 1 :].strip()))
        return question, sources
