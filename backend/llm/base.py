"""Provider interfaces + factory functions."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Iterator, Sequence

from django.conf import settings


class LLMProvider(ABC):
    """Chat-completion provider."""

    name: str = "base"

    @abstractmethod
    def generate(self, system: str, user: str, *, max_tokens: int = 512) -> str:
        """Return the full completion as text."""

    @abstractmethod
    def stream(self, system: str, user: str, *, max_tokens: int = 512) -> Iterator[str]:
        """Yield the completion in small string pieces (for SSE)."""

    @abstractmethod
    def estimate_tokens(self, text: str) -> int:
        """Rough token count used for per-tenant budgeting."""


class EmbeddingProvider(ABC):
    """Text -> fixed-dimension vector provider."""

    name: str = "base"
    dim: int = 0

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts; returns one vector per input, in order."""


def get_llm_provider() -> LLMProvider:
    backend = settings.LLM_BACKEND.lower()
    if backend == "gemini":
        from .gemini import GeminiLLM

        return GeminiLLM()
    from .fake import FakeLLM

    return FakeLLM()


def get_embedding_provider() -> EmbeddingProvider:
    backend = settings.EMBEDDING_BACKEND.lower()
    if backend == "sentence-transformers":
        from .st_embeddings import SentenceTransformerEmbeddings

        return SentenceTransformerEmbeddings()
    from .fake import DeterministicEmbeddings

    return DeterministicEmbeddings(dim=settings.EMBEDDING_DIM)


def batched(iterable: Iterable[str], size: int) -> Iterator[list[str]]:
    batch: list[str] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
