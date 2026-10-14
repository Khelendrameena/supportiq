"""Retrieval-quality eval harness: golden Q/A set over the sample knowledge base.

Run:  pytest evals/ -s        (the -s shows the per-question table)
CI:   runs automatically on every push (see .github/workflows/ci.yml).

The thresholds below are regression guards: if a retrieval change drops the
pipeline below them, CI fails. Tune them only with a written reason.
"""
import json
from pathlib import Path

import pytest
from django.test import override_settings
from kb.models import KnowledgeBase
from llm import get_embedding_provider
from retrieval.pipeline import answer_question
from tenants.models import Tenant, set_current_tenant

from .scoring import answer_relevance, faithfulness, keyword_recall

EVALS_DIR = Path(__file__).resolve().parent

MIN_MEAN_FAITHFULNESS = 0.70
# Baselines measured with the deterministic stub providers (2026-10-15):
# faithfulness=0.86 relevance=0.42 keyword_recall=0.73. Thresholds sit just
# below the measured baseline; they are regression guards, not aspirations.
MIN_MEAN_RELEVANCE = 0.40
MIN_MEAN_KEYWORD_RECALL = 0.70


def load_golden():
    return json.loads((EVALS_DIR / "golden.json").read_text())


@pytest.fixture
def eval_kb(db):
    """Fresh tenant + KB ingested from evals/sample_kb/*.md."""
    tenant = Tenant.objects.create(name="Eval Corp", slug="evalcorp")
    set_current_tenant(tenant)
    kb = KnowledgeBase.objects.create(tenant=tenant, name="Eval KB")
    from conftest import ingest_text

    for md_file in sorted((EVALS_DIR / "sample_kb").glob("*.md")):
        ingest_text(tenant, kb, md_file.stem, md_file.read_text(), filename=md_file.name)
    return tenant, kb


@pytest.mark.django_db
@override_settings(ABSTAIN_THRESHOLD=0.35)
def test_golden_eval(eval_kb, capsys):
    tenant, kb = eval_kb
    embedder = get_embedding_provider()
    golden = load_golden()

    from retrieval.pipeline import retrieve

    rows = []
    for item in golden:
        answer = answer_question(tenant.id, kb.id, item["question"])
        # Map citations back to chunk texts via a second retrieval pass.
        ranked, _ = retrieve(tenant.id, kb.id, item["question"])
        cited_indexes = {c.index for c in answer.citations}
        chunk_texts = [r.text for i, r in enumerate(ranked, start=1) if i in cited_indexes]

        f = faithfulness(answer.text, chunk_texts, item.get("abstain_expected", False), answer.abstained)
        rel = 1.0 if answer.abstained else answer_relevance(item["question"], answer.text, embedder)
        rec = keyword_recall(answer.text, item.get("must_contain", []))
        rows.append((item["id"], answer.abstained, round(f, 2), round(rel, 2), round(rec, 2),
                     answer.text[:80].replace("\n", " ")))

    with capsys.disabled():
        print(f"\n{'id':<18} {'abstained':<9} {'faithful':<8} {'relevant':<8} {'recall':<6} answer")
        for row in rows:
            print(f"{row[0]:<18} {str(row[1]):<9} {row[2]:<8} {row[3]:<8} {row[4]:<6} {row[5]}")

    mean_f = sum(r[2] for r in rows) / len(rows)
    mean_rel = sum(r[3] for r in rows) / len(rows)
    mean_rec = sum(r[4] for r in rows) / len(rows)
    with capsys.disabled():
        print(f"\nMEAN faithfulness={mean_f:.2f} relevance={mean_rel:.2f} keyword_recall={mean_rec:.2f}")

    assert mean_f >= MIN_MEAN_FAITHFULNESS, f"faithfulness regressed: {mean_f:.2f}"
    assert mean_rel >= MIN_MEAN_RELEVANCE, f"relevance regressed: {mean_rel:.2f}"
    assert mean_rec >= MIN_MEAN_KEYWORD_RECALL, f"keyword recall regressed: {mean_rec:.2f}"
