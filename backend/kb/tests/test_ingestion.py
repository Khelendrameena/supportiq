"""Ingestion pipeline: eager end-to-end, idempotency, failure handling."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from kb.models import Chunk, Document
from kb.tasks import ingest_document
from tenants.models import set_current_tenant

from conftest import SAMPLE_DOC, ingest_text


@pytest.mark.django_db
class TestIngestion:
    def test_upload_triggers_ingestion(self, client_a, kb_a):
        set_current_tenant(kb_a.tenant)
        upload = SimpleUploadedFile("handbook.txt", SAMPLE_DOC.encode(), content_type="text/plain")
        resp = client_a.post(
            "/api/kb/documents/upload/",
            {"kb": kb_a.id, "title": "Handbook", "file": upload},
            format="multipart",
        )
        assert resp.status_code == 201, resp.content
        # The middleware clears the thread-local tenant after each request,
        # so re-establish it before touching the ORM in test code.
        set_current_tenant(kb_a.tenant)
        doc = Document.objects.get(id=resp.json()["id"])
        # Celery eager mode (no Redis in tests): ingestion ran synchronously.
        assert doc.status == Document.Status.READY
        assert doc.chunk_count == Chunk.objects.filter(document=doc).count() > 0

    def test_duplicate_upload_is_idempotent(self, client_a, kb_a):
        set_current_tenant(kb_a.tenant)

        def upload():
            f = SimpleUploadedFile("handbook.txt", SAMPLE_DOC.encode(), content_type="text/plain")
            return client_a.post(
                "/api/kb/documents/upload/", {"kb": kb_a.id, "file": f}, format="multipart"
            )

        first = upload()
        second = upload()
        assert first.status_code == 201
        assert second.status_code == 200  # replay, not a duplicate
        assert second["X-Idempotent-Replay"] == "true"
        set_current_tenant(kb_a.tenant)
        assert Document.objects.filter(kb=kb_a).count() == 1

    def test_rerun_of_ready_document_is_noop(self, tenant_a, kb_a):
        doc, first = ingest_text(tenant_a, kb_a, "Handbook", SAMPLE_DOC)
        chunks_before = Chunk.objects.filter(document=doc).count()
        second = ingest_document(doc.id, tenant_id=str(tenant_a.id))
        assert second["status"] == "already_ready"
        assert Chunk.objects.filter(document=doc).count() == chunks_before

    def test_concurrent_ingestion_single_flight(self, tenant_a, kb_a):
        """A second worker racing the first sees the lock and stands down."""
        from django.core.cache import cache

        doc, _ = ingest_text(tenant_a, kb_a, "Handbook", SAMPLE_DOC)
        # Pretend the document went back to pending (redelivery scenario)
        # while another worker holds the lock.
        doc.status = Document.Status.PENDING
        doc.save(update_fields=["status"])
        cache.add(f"ingest-lock:{doc.id}", "1", 600)
        result = ingest_document(doc.id, tenant_id=str(tenant_a.id))
        assert result["status"] == "locked"
        cache.delete(f"ingest-lock:{doc.id}")

    def test_empty_file_marks_failed_with_error(self, tenant_a, kb_a):
        doc, _ = None, None
        from django.core.files.base import ContentFile
        from kb.tasks import compute_content_hash

        set_current_tenant(tenant_a)
        raw = b"   \n  "
        doc = Document.all_objects.create(
            tenant=tenant_a, kb=kb_a, title="empty",
            file=ContentFile(raw, name="empty.txt"),
            content_hash=compute_content_hash(raw),
        )
        with pytest.raises(ValueError, match="no extractable text"):
            ingest_document(doc.id, tenant_id=str(tenant_a.id))
        doc.refresh_from_db()
        assert doc.status == Document.Status.FAILED
        assert "no extractable text" in doc.error

    def test_document_status_endpoint(self, client_a, kb_a_ingested, tenant_a):
        set_current_tenant(tenant_a)
        doc = Document.objects.first()
        resp = client_a.get(f"/api/kb/documents/{doc.id}/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
