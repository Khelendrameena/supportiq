"""Retrieval: RRF fusion, hybrid search, abstention guard, tenant isolation."""
import pytest
from retrieval.bm25 import bm25_search
from retrieval.pipeline import answer_question, retrieve
from retrieval.rrf import reciprocal_rank_fusion
from retrieval.vector import vector_search
from tenants.models import set_current_tenant

from conftest import ingest_text


class TestRRF:
    def test_fusion_prefers_consensus(self):
        # Doc 1 ranks well in BOTH lists -> should win overall.
        fused = reciprocal_rank_fusion([[1, 2, 3], [2, 1, 3]])
        assert [cid for cid, _ in fused] == [1, 2, 3]

    def test_fusion_uses_ranks_not_scores(self):
        # A doc ranked #1 in one list beats #50 in another, regardless of
        # how the raw scores compared (they're on different scales).
        fused = reciprocal_rank_fusion([[7] + list(range(100, 150)), [5, 7]])
        assert fused[0][0] == 7

    def test_empty_lists(self):
        assert reciprocal_rank_fusion([[], []]) == []


@pytest.mark.django_db
class TestHybridRetrieval:
    def test_vector_search_finds_relevant_chunk(self, tenant_a, kb_a_ingested):
        from llm import get_embedding_provider

        vec = get_embedding_provider().embed(["how do I get my money back?"])[0]
        hits = vector_search(tenant_a.id, kb_a_ingested.id, vec, top_k=5)
        assert hits, "expected at least one vector hit"
        from kb.models import Chunk

        top_text = Chunk.all_objects.get(id=hits[0][0]).text
        assert "refund" in top_text.lower()

    def test_bm25_finds_keyword_chunk(self, tenant_a, kb_a_ingested):
        hits = bm25_search(tenant_a.id, kb_a_ingested.id, "refund money-back guarantee", top_k=5)
        assert hits, "expected at least one BM25 hit"
        from kb.models import Chunk

        assert "refund" in Chunk.all_objects.get(id=hits[0][0]).text.lower()

    def test_answer_is_cited_and_grounded(self, tenant_a, kb_a_ingested):
        answer = answer_question(tenant_a.id, kb_a_ingested.id, "What is the refund policy?")
        assert not answer.abstained
        assert answer.citations, "grounded answers must carry citations"
        assert "[1]" in answer.text or "[2]" in answer.text
        assert "30-day" in answer.text  # the actual fact from the KB

    def test_abstention_on_unknown_topic(self, tenant_a, kb_a_ingested):
        answer = answer_question(
            tenant_a.id, kb_a_ingested.id, "What is the capital of Assyria?"
        )
        assert answer.abstained
        assert answer.citations == []
        assert "don't have information" in answer.text

    def test_retrieval_is_tenant_scoped(self, tenant_a, tenant_b, kb_a_ingested):
        from kb.models import KnowledgeBase

        set_current_tenant(tenant_b)
        kb_b = KnowledgeBase.objects.create(tenant=tenant_b, name="Beta KB")
        ingest_text(tenant_b, kb_b, "Beta doc", "Beta Corp was founded in 2019 in Berlin.")
        # Tenant A must never see tenant B's chunks, even for a matching query.
        ranked, _timings = retrieve(tenant_a.id, kb_a_ingested.id, "founded Berlin")
        assert all(r.document_title != "Beta doc" for r in ranked)

    def test_retrieve_returns_timings(self, tenant_a, kb_a_ingested):
        _ranked, timings = retrieve(tenant_a.id, kb_a_ingested.id, "refund policy")
        assert set(timings) >= {"embed_ms", "vector_ms", "bm25_ms", "rerank_ms"}
        assert all(v >= 0 for v in timings.values())


@pytest.mark.django_db
class TestHallucinationGuard:
    """The two-tier abstention rule, tested directly."""

    def test_lexical_match_above_threshold_answers(self, tenant_a, kb_a_ingested):
        answer = answer_question(tenant_a.id, kb_a_ingested.id, "What is the refund policy?")
        assert not answer.abstained

    def test_embedding_only_weak_match_abstains(self, tenant_a, kb_a_ingested):
        # No shared content terms with any chunk; embedding similarity alone
        # must not be enough to answer.
        answer = answer_question(tenant_a.id, kb_a_ingested.id, "What is the capital of Assyria?")
        assert answer.abstained

    def test_guard_rule_unit(self):
        from django.test import override_settings
        from retrieval.pipeline import RankedChunk, _has_sufficient_evidence

        def chunk(text, score):
            return RankedChunk(chunk_id=1, document_id=1, document_title="d", ord=0, text=text, score=score)

        with override_settings(ABSTAIN_THRESHOLD=0.35, ABSTAIN_SEMANTIC_ONLY_THRESHOLD=0.55):
            # Lexical evidence + decent score -> answer.
            assert _has_sufficient_evidence("refund policy?", chunk("refund policy here", 0.40))
            # Weak score even with lexical evidence -> abstain.
            assert not _has_sufficient_evidence("refund policy?", chunk("refund policy here", 0.20))
            # Strong embedding-only match -> answer (high bar cleared).
            assert _has_sufficient_evidence("blorple wazzle?", chunk("totally unrelated words", 0.80))
            # Weak embedding-only match -> abstain.
            assert not _has_sufficient_evidence("blorple wazzle?", chunk("totally unrelated words", 0.40))
