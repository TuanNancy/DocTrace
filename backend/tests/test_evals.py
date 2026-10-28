"""Golden-set, retrieval, scoring and baseline tests; no provider/network calls."""
from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

import pytest

from app.core.config import AppConfig
from app.providers.usage import ProviderCall
from app.storage.base import RetrievedChunk
from evals import baseline as baseline_store
from evals.dataset import DEFAULT_PATH, GoldenSetError, dataset_sha256, load
from evals.evaluator import detect_refusal, score_case, summarize, threshold_failures
from evals.provider import ExtractiveProvider
from evals.retrieval import (
    InMemoryVectorStore, LexicalRetriever, page_chunks, terms,
)
from evals.runner import EvalUsage, EvaluationError, run_live, run_smoke, usage_totals


@pytest.fixture(scope="module")
def golden():
    return load(DEFAULT_PATH)


def test_golden_set_is_stable_and_has_bilingual_coverage(golden):
    assert len(golden.documents) == 3
    assert len(golden.cases) == 28
    assert {case.language for case in golden.cases} == {"vi", "en"}
    assert {case.category for case in golden.cases} >= {"lookup", "multi_hop", "overview", "refusal"}
    assert dataset_sha256(golden) == dataset_sha256(load(DEFAULT_PATH))


def test_loader_rejects_evidence_not_present_on_the_declared_page(tmp_path):
    source = DEFAULT_PATH.read_text(encoding="utf-8")
    broken = source.replace(
        "        text: 24 days of paid annual leave", "        text: this text is absent",
    )
    path = tmp_path / "broken.yaml"
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(GoldenSetError, match="evidence is not present"):
        load(path)


def test_lexical_retrieval_is_deterministic_and_overview_reads_every_page(golden):
    retriever = LexicalRetriever(golden.documents)
    document = golden.document("handbook")
    result = __import__("asyncio").run(
        retriever.retrieve("How many annual leave days?", "handbook", top_k=2)
    )
    assert result[0].page == 2
    assert result[0].score >= result[1].score
    overview = __import__("asyncio").run(
        retriever.retrieve("Summarize this PDF", "handbook", top_k=1)
    )
    assert [chunk.page for chunk in overview] == [1, 2, 3, 4, 5]


def test_terms_are_unicode_aware_and_ignore_question_words():
    assert "leave" in terms("How many annual leave days?")
    assert "nhiều" not in terms("Bao nhiêu ngày phép?")
    assert "ngày" in terms("Bao nhiêu ngày phép?")
    assert "mfa" not in terms("MFA prompt")
    assert "multi" in terms("MFA prompt")


def test_extractive_provider_refuses_unrelated_questions_and_cites_answers():
    provider = ExtractiveProvider()
    context = (
        "[1] [Trang 1]\nThe Free plan includes 10 questions per month and 5 documents.\n\n"
        "[2] [Trang 2]\nThe Pro plan includes 100 questions per month."
    )
    answer = __import__("asyncio").run(provider.generate_with_context(
        "How many questions does the Free plan include?", context, language="en",
    ))
    assert "10 questions" in answer and "[1]" in answer
    refusal = __import__("asyncio").run(provider.generate_with_context(
        "Does the Pro plan include a dedicated phone hotline?", context, language="en",
    ))
    assert detect_refusal(refusal)


def test_in_memory_store_ranks_by_cosine_and_scopes_documents():
    import asyncio

    store = InMemoryVectorStore(AppConfig(model="eval"))
    asyncio.run(store.connect())
    asyncio.run(store.insert_chunks("doc-a", [
        {"chunk_id": "a1", "text": "leave", "page": 1, "source": "a.pdf"},
        {"chunk_id": "a2", "text": "security", "page": 2, "source": "a.pdf"},
    ], [[1.0, 0.0], [0.0, 1.0]], user_id="eval"))
    asyncio.run(store.insert_chunks("doc-b", [
        {"chunk_id": "b1", "text": "other", "page": 1, "source": "b.pdf"},
    ], [[1.0, 0.0]], user_id="eval"))

    result = asyncio.run(store.search_chunks(
        [1.0, 0.0], "doc-a", top_k=2, min_score=0.5, user_id="eval",
    ))
    assert [chunk.chunk_id for chunk in result] == ["a1"]
    all_chunks = asyncio.run(store.get_document_chunks("doc-a", user_id="eval"))
    assert [chunk.page for chunk in all_chunks] == [1, 2]
    assert asyncio.run(store.get_document_chunks("missing", user_id="eval")) == []
    assert asyncio.run(store.search_chunks(
        [1.0, 0.0], "doc-b", top_k=2, min_score=0.5, user_id="eval",
    ))[0].chunk_id == "b1"


def test_scoring_reports_missing_citations_refusals_and_forbidden_text(golden):
    case = next(item for item in golden.cases if item.id == "handbook-receipts")
    chunks = [RetrievedChunk("r1", "handbook", "Submit receipts within 30 days.", 4, "handbook", 0.9)]
    correct = score_case(
        case, chunks, chunks, "Receipts are due within 30 days [1].",
        latency_ms=1, first_token_ms=1, cost_micros=None, cost_known_micros=0,
        unknown_cost_calls=0, provider_calls=0,
    )
    assert correct.passed and correct.answer_correct
    missing_citation = score_case(
        case, chunks, chunks, "Receipts are due within 30 days.",
        latency_ms=1, first_token_ms=1, cost_micros=None, cost_known_micros=0,
        unknown_cost_calls=0, provider_calls=0,
    )
    assert not missing_citation.passed
    assert "missing_citation" in missing_citation.failure_reasons
    invalid = score_case(
        case, chunks, chunks, "Receipts are due within 30 days [2].",
        latency_ms=1, first_token_ms=1, cost_micros=None, cost_known_micros=0,
        unknown_cost_calls=0, provider_calls=0,
    )
    assert "invalid_citation" in invalid.failure_reasons
    leave_case = next(item for item in golden.cases if item.id == "handbook-leave-days")
    leave_chunks = [RetrievedChunk(
        "l1", "handbook", "Full-time employees receive 24 days of paid annual leave.", 2,
        "handbook", 0.9,
    )]
    forbidden = score_case(
        leave_case, leave_chunks, leave_chunks, "Employees receive 24 days, unlimited [1].",
        latency_ms=1, first_token_ms=1, cost_micros=None, cost_known_micros=0,
        unknown_cost_calls=0, provider_calls=0,
    )
    assert "forbidden_text" in forbidden.failure_reasons

    refusal_case = next(item for item in golden.cases if item.id == "handbook-unanswerable-stock")
    refusal = score_case(
        refusal_case, chunks, chunks, "The document does not contain information about that.",
        latency_ms=1, first_token_ms=1, cost_micros=None, cost_known_micros=0,
        unknown_cost_calls=0, provider_calls=0,
    )
    assert refusal.passed and refusal.answer_correct
    answered = score_case(
        refusal_case, chunks, chunks, "Vesting is four years [1].",
        latency_ms=1, first_token_ms=1, cost_micros=None, cost_known_micros=0,
        unknown_cost_calls=0, provider_calls=0,
    )
    assert "expected_refusal" in answered.failure_reasons


def test_summary_and_thresholds_are_json_serializable(golden):
    artifact = run_smoke(golden, DEFAULT_PATH, top_k=3)
    summary = artifact["summary"]
    assert summary["total_cases"] == 28
    assert summary["pass_rate"] == 1.0
    assert threshold_failures(summary, baseline_store.THRESHOLDS["smoke"]) == []
    json.dumps(summary)

    broken = dict(summary)
    broken["pass_rate"] = 0.1
    assert threshold_failures(broken, baseline_store.THRESHOLDS["smoke"])


def test_baseline_update_checks_dataset_and_thresholds(golden, tmp_path):
    artifact = run_smoke(golden, DEFAULT_PATH, top_k=3)
    path = tmp_path / "baseline.json"
    baseline_store.update(path, artifact)
    payload = baseline_store.load(path)
    assert payload["dataset_sha256"] == artifact["dataset"]["sha256"]
    assert payload["smoke"]["metrics"]["pass_rate"] == 1.0
    check = baseline_store.check(payload, "smoke", artifact)
    assert check["status"] == "pass" and check["failures"] == []

    artifact["summary"]["pass_rate"] = 0.2
    assert baseline_store.check(payload, "smoke", artifact)["status"] == "fail"
    artifact["dataset"]["sha256"] = "changed"
    assert any(
        "dataset changed" in failure.casefold()
        for failure in baseline_store.check(payload, "smoke", artifact)["failures"]
    )


def test_usage_totals_treat_missing_cost_as_unknown():
    known = ProviderCall(kind="answer", model="m")
    known.cost_usd = Decimal("0.000045")
    missing = ProviderCall(kind="answer", model="m")
    assert usage_totals([known, missing]) == (45, 1)
    assert usage_totals([]) == (0, 0)


def test_live_evaluation_requires_a_budget_before_creating_a_provider(golden):
    with pytest.raises(EvaluationError, match="budget"):
        run_live(golden, DEFAULT_PATH, AppConfig(model="m", embedding_model="e"), budget_micros=0)


def test_cli_writes_an_artifact_without_network(golden, tmp_path):
    from evals.__main__ import main

    output = tmp_path / "smoke.json"
    assert main(["--mode", "smoke", "--no-baseline", "--output", str(output)]) == 0
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["mode"] == "smoke"
    assert artifact["summary"]["passed"] == 28
    assert artifact["baseline"] is None
