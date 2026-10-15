"""KB API serializers."""
from django.db import IntegrityError, transaction
from rest_framework import serializers

from .models import Document, KnowledgeBase
from .tasks import compute_content_hash, ingest_document


class TenantScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """PK field whose queryset is built per-request (tenant-aware).

    DRF evaluates a `queryset=` argument once at import time; with the
    tenant-aware manager that would permanently freeze whatever tenant (or
    none) was active during import. Overriding get_queryset() defers it to
    validation time, inside the request's tenant scope.
    """

    def get_queryset(self):
        return KnowledgeBase.objects.all()


class KnowledgeBaseSerializer(serializers.ModelSerializer):
    document_count = serializers.SerializerMethodField()

    class Meta:
        model = KnowledgeBase
        fields = ["id", "name", "description", "document_count", "created_at"]
        read_only_fields = ["id", "created_at"]

    def get_document_count(self, obj):
        return obj.documents.count()


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = ["id", "kb", "title", "status", "error", "chunk_count", "created_at"]
        read_only_fields = ["id", "status", "error", "chunk_count", "created_at"]


class DocumentUploadSerializer(serializers.Serializer):
    # NOTE: queryset is resolved per-request via get_queryset(), NOT at class
    # definition time — the tenant-aware manager would otherwise freeze the
    # import-time tenant into the field forever.
    kb = TenantScopedPrimaryKeyRelatedField()
    title = serializers.CharField(max_length=300, required=False)
    file = serializers.FileField()

    def create(self, validated_data):
        from tenants.models import get_current_tenant

        tenant = get_current_tenant()
        upload = validated_data["file"]
        raw = upload.read()
        content_hash = compute_content_hash(raw)
        upload.seek(0)
        try:
            # Savepoint: the IntegrityError below must not poison the outer
            # transaction (tests, or any atomic caller).
            with transaction.atomic():
                doc = Document.all_objects.create(
                    tenant=tenant,
                    kb=validated_data["kb"],
                    title=validated_data.get("title") or upload.name,
                    file=upload,
                    content_hash=content_hash,
                )
        except IntegrityError:
            # Idempotent re-upload: identical content already ingested/queued.
            doc = Document.objects.get(kb=validated_data["kb"], content_hash=content_hash)
            return doc, False
        # Queue background ingestion. The tenant travels explicitly in the
        # task args (JSON-safe): a worker has no request/thread-local, and
        # Postgres RLS hides tenant rows until the session variable is armed.
        ingest_document.delay(doc.id, tenant_id=str(tenant.id))
        return doc, True
