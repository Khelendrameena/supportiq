"""Measure real cached vs uncached chat latency.

Usage:
    python manage.py benchmark_cache --tenant acme --kb 1 \\
        --question "What is the refund policy?" --question "How do I reset my password?"

Prints a table with cold (full pipeline) vs warm (semantic cache) latency in
ms. These are measured numbers — paste them into the README honestly.
"""
import time

from django.core.management.base import BaseCommand, CommandError
from kb.models import KnowledgeBase
from tenants.models import Tenant, set_current_tenant

from chat.cache import invalidate_tenant_cache
from chat.services import stream_chat_events


class Command(BaseCommand):
    help = "Benchmark semantic-cache latency: cold run vs warm run per question."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="tenant slug")
        parser.add_argument("--kb", required=True, type=int, help="knowledge base id")
        parser.add_argument("--question", action="append", required=True, dest="questions")

    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.get(slug=options["tenant"])
        except Tenant.DoesNotExist:
            raise CommandError(f"no tenant with slug {options['tenant']!r}")
        set_current_tenant(tenant)
        kb = KnowledgeBase.objects.get(id=options["kb"])
        # A system user for the benchmark run.
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(tenant=tenant).first()
        if user is None:
            raise CommandError("tenant has no users; register one first")

        self.stdout.write(f"{'question':<50} {'cold_ms':>10} {'warm_ms':>10} {'speedup':>8}")
        for question in options["questions"]:
            invalidate_tenant_cache(tenant.id)  # force a cold run
            cold = self._run(tenant, user, kb, question)
            warm = self._run(tenant, user, kb, question)  # served from cache
            speedup = cold / warm if warm else float("inf")
            self.stdout.write(f"{question[:48]:<50} {cold:>10.1f} {warm:>10.1f} {speedup:>7.1f}x")

    @staticmethod
    def _run(tenant, user, kb, question):
        t0 = time.perf_counter()
        for _event in stream_chat_events(tenant, user, kb, question):
            pass
        return (time.perf_counter() - t0) * 1000
