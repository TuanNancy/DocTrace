"""Golden-set scoring: retrieval, citations, refusal and answer checks.

Scoring is deliberately deterministic and explainable. A case records why it
failed instead of collapsing everything into a single opaque score.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import re
from typing import Iterable, Optional

from app.storage.base import RetrievedChunk
from evals.schema import GoldenCase

_CITATION = re.compile(r"\[(\d+)\]")
_REFUSAL_MARKERS = (
    "does not contain information", "does not mention", "no information",
    "not enough information", "cannot answer", "can't answer", "unable to answer",
    "không có thông tin", "không đề cập", "không tìm thấy", "không đủ thông tin",
    "tài liệu không",
)


def normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def detect_refusal(answer: str) -> bool:
    value = normalized(answer)
    return any(marker in value for marker in _REFUSAL_MARKERS)


def citation_ids(answer: str) -> list[int]:
    seen, result = set(), []
    for match in _CITATION.finditer(answer):
        number = int(match.group(1))
        if number not in seen:
            seen.add(number)
            result.append(number)
    return result


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    return numerator / denominator if denominator else None


@dataclass
class CaseResult:
    case_id: str
    doc: str
    category: str
    language: str
    query: str
    answer: str
    refusal: bool
    retrieved: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    retrieved_pages: list[int] = field(default_factory=list)
    source_pages: list[int] = field(default_factory=list)
    expected_pages: list[int] = field(default_factory=list)
    citations: list[int] = field(default_factory=list)
    invalid_citations: list[int] = field(default_factory=list)
    must_include_missing: list[str] = field(default_factory=list)
    must_not_include_found: list[str] = field(default_factory=list)
    retrieval_recall: Optional[float] = None
    retrieval_precision: Optional[float] = None
    reciprocal_rank: Optional[float] = None
    citation_precision: Optional[float] = None
    citation_recall: Optional[float] = None
    answer_correct: bool = False
    passed: bool = False
    failure_reasons: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    first_token_ms: Optional[float] = None
    cost_micros: Optional[int] = None
    cost_known_micros: int = 0
    unknown_cost_calls: int = 0
    provider_calls: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _source(chunk: RetrievedChunk) -> dict:
    return {
        "chunk_id": chunk.chunk_id,
        "page": chunk.page,
        "source": chunk.source,
        "score": chunk.score,
        "text": chunk.text,
    }


def score_case(
    case: GoldenCase, retrieved: list[RetrievedChunk], sources: list[RetrievedChunk],
    answer: str, *, latency_ms: float, first_token_ms: Optional[float],
    cost_micros: Optional[int], cost_known_micros: int, unknown_cost_calls: int,
    provider_calls: int,
) -> CaseResult:
    expected_pages = list(dict.fromkeys(item.page for item in case.evidence))
    retrieved_pages = list(dict.fromkeys(chunk.page for chunk in retrieved))
    source_pages = list(dict.fromkeys(chunk.page for chunk in sources))
    citations = citation_ids(answer)
    invalid = [number for number in citations if not 1 <= number <= len(sources)]
    cited_pages = list(dict.fromkeys(
        sources[number - 1].page for number in citations if number not in invalid
    ))
    value = normalized(answer)
    missing = [item for item in case.must_include if normalized(item) not in value]
    forbidden = [item for item in case.must_not_include if normalized(item) in value]
    refusal = detect_refusal(answer)

    retention = _ratio(len(set(expected_pages) & set(retrieved_pages)), len(expected_pages))
    precision = _ratio(len(set(expected_pages) & set(retrieved_pages)), len(retrieved_pages))
    reciprocal = None
    if expected_pages and retrieved_pages:
        reciprocal = next(
            (1 / rank for rank, page in enumerate(retrieved_pages, 1) if page in expected_pages),
            0.0,
        )
    citation_precision = None
    citation_recall = None
    if expected_pages:
        citation_precision = (
            len([number for number in citations if number not in invalid
                 and sources[number - 1].page in expected_pages]) / len(citations)
            if citations else 0.0
        )
        citation_recall = _ratio(len(set(expected_pages) & set(cited_pages)), len(expected_pages))

    reasons = []
    answer_correct = False
    if case.expected_refusal:
        answer_correct = refusal and not forbidden
        if not refusal:
            reasons.append("expected_refusal")
        if forbidden:
            reasons.append("forbidden_claim")
    else:
        answer_correct = not refusal and not missing and not forbidden
        if refusal:
            reasons.append("unexpected_refusal")
        if missing:
            reasons.append("missing_required_text")
        if forbidden:
            reasons.append("forbidden_text")
        if not citations:
            reasons.append("missing_citation")
        if invalid:
            reasons.append("invalid_citation")
        if citation_precision is not None and citation_precision < 0.5:
            reasons.append("low_citation_precision")
        if citation_recall is not None and citation_recall < 1.0:
            reasons.append("incomplete_citation_recall")
        if retention is not None and retention < 1.0:
            reasons.append("incomplete_retrieval_recall")

    return CaseResult(
        case_id=case.id, doc=case.doc, category=case.category, language=case.language,
        query=case.query, answer=answer, refusal=refusal,
        retrieved=[_source(chunk) for chunk in retrieved],
        sources=[_source(chunk) for chunk in sources],
        retrieved_pages=retrieved_pages, source_pages=source_pages,
        expected_pages=expected_pages, citations=citations, invalid_citations=invalid,
        must_include_missing=missing, must_not_include_found=forbidden,
        retrieval_recall=retention, retrieval_precision=precision,
        reciprocal_rank=reciprocal, citation_precision=citation_precision,
        citation_recall=citation_recall, answer_correct=answer_correct,
        passed=not reasons, failure_reasons=reasons,
        latency_ms=latency_ms, first_token_ms=first_token_ms,
        cost_micros=cost_micros, cost_known_micros=cost_known_micros,
        unknown_cost_calls=unknown_cost_calls, provider_calls=provider_calls,
    )


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def _percentile(values: Iterable[float], percentile: float) -> Optional[float]:
    present = sorted(values)
    if not present:
        return None
    index = max(0, math.ceil(percentile / 100 * len(present)) - 1)
    return round(present[index], 2)


def summarize(results: list[CaseResult]) -> dict:
    answerable = [result for result in results if result.expected_pages]
    refusals = [result for result in results if not result.expected_pages]
    known = sum(result.cost_known_micros for result in results)
    unknown = sum(result.unknown_cost_calls for result in results)
    return {
        "total_cases": len(results),
        "passed": sum(result.passed for result in results),
        "pass_rate": _mean([1.0 if result.passed else 0.0 for result in results]),
        "answer_accuracy": _mean([1.0 if result.answer_correct else 0.0 for result in answerable]),
        "refusal_accuracy": _mean([1.0 if result.answer_correct else 0.0 for result in refusals]),
        "retrieval_recall": _mean([result.retrieval_recall for result in answerable]),
        "retrieval_precision": _mean([result.retrieval_precision for result in answerable]),
        "mrr": _mean([result.reciprocal_rank for result in answerable]),
        "citation_precision": _mean([result.citation_precision for result in answerable]),
        "citation_recall": _mean([result.citation_recall for result in answerable]),
        "latency_p50_ms": _percentile([result.latency_ms for result in results], 50),
        "latency_p95_ms": _percentile([result.latency_ms for result in results], 95),
        "first_token_p50_ms": _percentile(
            [result.first_token_ms for result in results if result.first_token_ms is not None], 50,
        ),
        "first_token_p95_ms": _percentile(
            [result.first_token_ms for result in results if result.first_token_ms is not None], 95,
        ),
        "cost_known_micros": known,
        "unknown_cost_calls": unknown,
        "cost_micros": known if unknown == 0 else None,
        "cost_per_case_micros": round(known / len(results)) if results else None,
    }


def threshold_failures(summary: dict, thresholds: dict) -> list[str]:
    failures = []
    for key, minimum in thresholds.items():
        if key.startswith("min_"):
            metric = key[4:]
            value = summary.get(metric)
            if value is None or value + 1e-9 < minimum:
                failures.append(f"{metric}={value!r} is below {minimum}")
        elif key.startswith("max_"):
            metric = key[4:]
            value = summary.get(metric)
            if value is not None and value > minimum:
                failures.append(f"{metric}={value!r} is above {minimum}")
    return failures
