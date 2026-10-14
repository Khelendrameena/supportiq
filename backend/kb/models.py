"""Knowledge-base models.

Embedding storage is backend-conditional:
  - Postgres: pgvector `vector(dim)` column + HNSW index (production path).
  - SQLite:   packed float32 blob (local dev / tests). The retrieval layer
    brute-forces cosine over these — correct, just slower; fine for dev data.

Both paths store the same vectors, so behavior is comparable.
"""
import struct

from django.conf import settings
from django.db import models
from tenants.models import TenantAwareModel

if settings.IS_POSTGRES:
    from pgvector.django import HnswIndex, VectorField

    def embedding_field():
        return VectorField(dimensions=settings.EMBEDDING_DIM, null=True)

    def embedding_index():
        return HnswIndex(
            name="kb_chunk_embedding_hnsw",
            fields=["embedding"],
            m=16,
            ef_construction=64,
            opclasses=["vector_cosine_ops"],
        )
else:

    def embedding_field():
        return models.BinaryField(null=True)

    def embedding_index():
        # No vector index available on SQLite; retrieval falls back to
        # brute-force cosine in Python (see retrieval/vector.py).
        return models.Index(name="kb_chunk_doc_idx", fields=["document"])


def pack_embedding(vec) -> bytes:
    """Pack a float vector for the SQLite blob column."""
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_embedding(blob, dim: int) -> list:
    return list(struct.unpack(f"{dim}f", blob))


class KnowledgeBase(TenantAwareModel):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name


class Document(TenantAwareModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=300)
    file = models.FileField(upload_to="kb_docs/")
    # sha256 of the raw file bytes. The idempotency key for ingestion:
    # re-uploading identical content never re-ingests.
    content_hash = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True, default="")
    chunk_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Same file uploaded twice to one KB: second upload is a no-op.
        constraints = [
            models.UniqueConstraint(fields=["kb", "content_hash"], name="uq_doc_kb_content_hash")
        ]


class Chunk(TenantAwareModel):
    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="chunks")
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    ord = models.IntegerField(help_text="Chunk order within the document")
    text = models.TextField()
    token_count = models.IntegerField(default=0)
    embedding = embedding_field()

    class Meta:
        indexes = [embedding_index()]
        ordering = ["document_id", "ord"]
