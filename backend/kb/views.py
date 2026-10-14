"""Knowledge-base API: CRUD for KBs, upload + status for documents."""
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Document, KnowledgeBase
from .serializers import DocumentSerializer, DocumentUploadSerializer, KnowledgeBaseSerializer
from .tasks import ingest_document


class KnowledgeBaseViewSet(viewsets.ModelViewSet):
    serializer_class = KnowledgeBaseSerializer

    def get_queryset(self):
        # Built per-request: the tenant-aware manager scopes by the
        # thread-local tenant, which is only valid inside a request.
        # (A class-level queryset would freeze the import-time tenant.)
        return KnowledgeBase.objects.all().order_by("-created_at")


class DocumentViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    serializer_class = DocumentSerializer

    def get_queryset(self):
        # Per-request for the same reason as KnowledgeBaseViewSet.
        qs = Document.objects.all().order_by("-created_at")
        kb_id = self.request.query_params.get("kb")
        return qs.filter(kb_id=kb_id) if kb_id else qs

    @action(detail=False, methods=["post"], url_path="upload")
    def upload(self, request):
        serializer = DocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        doc, created = serializer.save()
        return Response(
            DocumentSerializer(doc).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            headers={"X-Idempotent-Replay": "true"} if not created else {},
        )

    @action(detail=True, methods=["post"], url_path="reingest")
    def reingest(self, request, pk=None):
        doc = self.get_object()
        ingest_document.delay(doc.id)
        return Response({"status": "queued", "document_id": doc.id}, status=status.HTTP_202_ACCEPTED)
