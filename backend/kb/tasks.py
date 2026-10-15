"""Knowledge-base ingestion pipeline (Celery).

Idempotency design — ingestion must be safe to retry and to trigger twice:
  1. Content hash: Document has a UNIQUE (kb, content_hash) constraint, so a
     duplicate upload raises IntegrityError instead of creating a second row.
  2. Status gate: if the document is already READY, the task returns early.
  3. Distributed lock: `ingest-lock:{document_id}` in the cache prevents two
     workers from ingesting the same document concurrently (double-click
     upload, or broker redelivery).
  4. Autoretry: transient infra failures (Redis/DB blips) retry with backoff.
"""
import hashlib
import io
import logging
import os

import redis as redis_lib
from celery import shared_task
from django.core.cache import cache
from django.db import OperationalError, transaction

from llm import get_embedding_provider
from llm.base import batched
from tenants.models import Tenant, clear_current_tenant, get_current_tenant, set_current_tenant

from .chunking import chunk_text
from .models import Chunk, Document, pack_embedding

logger = logging.getLogger("supportiq.ingestion")

LOCK_TTL_SECONDS = 10 * 60
EMBED_BATCH_SIZE = 32


def extract_text(filename: str, raw: bytes) -> str:
    """Extract plain text from an uploaded file (pdf / markdown / text)."""
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    # .md, .txt and anything else: treat as utf-8 text.
    return raw.decode("utf-8", errors="replace")


def compute_content_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@shared_task(
    bind=True,
    autoretry_for=(redis_lib.exceptions.ConnectionError, OperationalError),
    retry_kwargs={"max_retries": 3, "countdown": 10},
    retry_backoff=True,
)
def ingest_document(self, document_id: int, tenant_id: str | None = None) -> dict:
    # Tasks run outside a request: no tenant in thread-local. The tenant is
    # passed explicitly (JSON-safe string) because Postgres RLS applies to
    # EVERY query regardless of ORM manager -- the "unscoped" document load
    # below would be invisible without the session variable armed first.
    # (The identity tables aren't RLS-covered, so the Tenant lookup itself
    # always works.)
    if tenant_id is not None:
        set_current_tenant(Tenant.objects.get(id=tenant_id))
    # Save/restore the caller's tenant: in eager mode (tests) the task runs
    # inline on the caller's thread, and on a real worker the DB connection
    # is reused across tasks -- either way we must not leave another
    # tenant's RLS identity behind when we finish.
    previous_tenant = get_current_tenant()
    if previous_tenant is None:
        raise RuntimeError(
            "ingest_document requires a tenant: pass tenant_id or set one "
            "before calling (without it, RLS hides every tenant row)."
        )
    try:
        doc = Document.all_objects.select_related("tenant", "kb").get(id=document_id)
        return _ingest_guarded(self, doc)
    finally:
        set_current_tenant(previous_tenant)


def _ingest_guarded(self, doc: Document) -> dict:
    document_id = doc.id
    if doc.status == Document.Status.READY:
        logger.info("ingestion skipped: already ready", extra={"document_id": document_id})
        return {"status": "already_ready", "document_id": document_id}

    lock_key = f"ingest-lock:{document_id}"
    if not cache.add(lock_key, "1", LOCK_TTL_SECONDS):
        logger.info("ingestion skipped: lock held", extra={"document_id": document_id})
        return {"status": "locked", "document_id": document_id}

    try:
        return _ingest(doc)
    finally:
        cache.delete(lock_key)


def _ingest(doc: Document) -> dict:
    doc.status = Document.Status.PROCESSING
    doc.error = ""
    doc.save(update_fields=["status", "error"])
    logger.info("ingestion started", extra={"document_id": doc.id, "kb_id": doc.kb_id})

    try:
        with doc.file.open("rb") as f:
            raw = f.read()
        text = extract_text(doc.file.name, raw)
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("no extractable text found in file")

        embedder = get_embedding_provider()
        chunk_rows = []
        for batch in batched(chunks, EMBED_BATCH_SIZE):
            vectors = embedder.embed(batch)
            for ord_, (piece, vec) in enumerate(zip(batch, vectors)):
                chunk_rows.append(
                    Chunk(
                        tenant=doc.tenant,
                        kb=doc.kb,
                        document=doc,
                        ord=len(chunk_rows),
                        text=piece,
                        token_count=max(1, len(piece) // 4),
                        embedding=_store_vector(vec),
                    )
                )

        with transaction.atomic():
            # Delete any partial chunks from a previous failed attempt, then
            # write the new set atomically: readers never see half a document.
            Chunk.all_objects.filter(document=doc).delete()
            Chunk.all_objects.bulk_create(chunk_rows, batch_size=500)
            doc.status = Document.Status.READY
            doc.chunk_count = len(chunk_rows)
            doc.save(update_fields=["status", "chunk_count"])

        logger.info(
            "ingestion complete",
            extra={"document_id": doc.id, "chunks": len(chunk_rows)},
        )
        return {"status": "ready", "document_id": doc.id, "chunks": len(chunk_rows)}
    except Exception as exc:  # noqa: BLE001 - mark failed, keep the error visible
        doc.status = Document.Status.FAILED
        doc.error = f"{type(exc).__name__}: {exc}"[:2000]
        doc.save(update_fields=["status", "error"])
        logger.exception("ingestion failed", extra={"document_id": doc.id})
        raise


def _store_vector(vec):
    """Convert an embedding to the column type of the active database."""
    from django.conf import settings

    if settings.IS_POSTGRES:
        return list(vec)  # pgvector accepts a plain list of floats
    from .models import pack_embedding

    return pack_embedding(list(vec))
