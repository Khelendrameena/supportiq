"""Initial migration: KnowledgeBase, Document, Chunk.

The embedding column type is backend-conditional (see kb/models.py):
pgvector on Postgres, packed blob on SQLite.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def _embedding_field():
    if settings.IS_POSTGRES:
        from pgvector.django import VectorField

        return VectorField(dimensions=settings.EMBEDDING_DIM, null=True)
    return models.BinaryField(null=True)


def _embedding_index():
    if settings.IS_POSTGRES:
        from pgvector.django import HnswIndex

        return HnswIndex(
            name="kb_chunk_embedding_hnsw",
            fields=["embedding"],
            m=16,
            ef_construction=64,
            opclasses=["vector_cosine_ops"],
        )
    return models.Index(name="kb_chunk_doc_idx", fields=["document"])


class Migration(migrations.Migration):
    initial = True
    dependencies = [("tenants", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="KnowledgeBase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="tenants.tenant")),
                ("name", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="Document",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="tenants.tenant")),
                ("kb", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="documents", to="kb.knowledgebase")),
                ("title", models.CharField(max_length=300)),
                ("file", models.FileField(upload_to="kb_docs/")),
                ("content_hash", models.CharField(db_index=True, max_length=64)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("processing", "Processing"), ("ready", "Ready"), ("failed", "Failed")], default="pending", max_length=16)),
                ("error", models.TextField(blank=True, default="")),
                ("chunk_count", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="Chunk",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="tenants.tenant")),
                ("kb", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="chunks", to="kb.knowledgebase")),
                ("document", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="chunks", to="kb.document")),
                ("ord", models.IntegerField(help_text="Chunk order within the document")),
                ("text", models.TextField()),
                ("token_count", models.IntegerField(default=0)),
                ("embedding", _embedding_field()),
            ],
            options={"ordering": ["document_id", "ord"], "indexes": [_embedding_index()]},
        ),
        migrations.AddConstraint(
            model_name="document",
            constraint=models.UniqueConstraint(fields=("kb", "content_hash"), name="uq_doc_kb_content_hash"),
        ),
    ]
