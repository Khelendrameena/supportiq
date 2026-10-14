"""Initial migration: Conversation, Message."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("kb", "0001_initial"),
        ("tenants", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Conversation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="tenants.tenant")),
                ("kb", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="conversations", to="kb.knowledgebase")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="conversations", to=settings.AUTH_USER_MODEL)),
                ("title", models.CharField(default="", max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="Message",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="tenants.tenant")),
                ("conversation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="messages", to="chat.conversation")),
                ("role", models.CharField(choices=[("user", "User"), ("assistant", "Assistant")], max_length=16)),
                ("text", models.TextField()),
                ("citations", models.JSONField(blank=True, default=list)),
                ("tokens_used", models.IntegerField(default=0)),
                ("latency_ms", models.FloatField(default=0.0)),
                ("cache_hit", models.BooleanField(default=False)),
                ("abstained", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["created_at"]},
        ),
    ]
