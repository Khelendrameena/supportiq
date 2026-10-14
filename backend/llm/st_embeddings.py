"""Optional real embeddings via sentence-transformers.

Activated with EMBEDDING_BACKEND=sentence-transformers. Requires the
`sentence-transformers` package (install separately — it pulls torch).
Dimension is read from the loaded model; EMBEDDING_DIM should match.
"""
from __future__ import annotations

from typing import Sequence

from django.conf import settings

from .base import EmbeddingProvider


class SentenceTransformerEmbeddings(EmbeddingProvider):
    name = "sentence-transformers"

    def __init__(self):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed. pip install sentence-transformers "
                "or set EMBEDDING_BACKEND=deterministic."
            ) from exc
        model_name = settings.SENTENCE_TRANSFORMER_MODEL
        self._model = SentenceTransformer(model_name)
        self.dim = self._model.get_sentence_embedding_dimension()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.encode(list(texts), normalize_embeddings=True)
        return [list(map(float, v)) for v in vectors]
