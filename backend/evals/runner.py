"""Run the golden set with offline smoke retrieval or live providers."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Iterable, Optional

from starlette.concurrency import run_in_threadpool

from app.ai.budget import budget_for
from app.ai.document_summary import is_document_overview
from app.ai.rag_pipeline import RAGPipeline
from app.ai.routing import choose_route
from app.core.config import AppConfig
from app.providers.factory import create_chat_provider
from app.providers.embeddings import get_embedder
from app.providers.usage import ProviderCall
from app.storage.base import RetrievedChunk
from evals.dataset import dataset_sha256
from evals.evaluator import CaseResult, score_case, summarize
from evals.provider import ExtractiveProvider
from evals.retrieval import InMemoryVectorStore, LexicalRetriever, build_vector_index
from evals.schema import GoldenCase, GoldenSet


class EvaluationError(RuntimeError):
    pass


class EvalUsage:
    """In-memory metering with the same start/flush contract as UsageCollector."""

    def __init__(self):
        self.calls: list[ProviderCall] = []

    def start(self, kind: str, model: str) -> ProviderCall:
        call = ProviderCall(kind=kind, model=model or "unknown")
        self.calls.append(call)
        return call

    async def flush(self) -> None:
        return None


def usage_totals(calls: Iterable[ProviderCall]) -> tuple[int, int]:
    known, unknown = 0, 0
    for call in calls:
        cost = call.cost_micros
        if cost is None:
            unknown += 1
        else:
            known += cost
    return known, unknown


class PipelineRetriever:
    def __init__(self, pipeline: RAGPipeline):
        self.pipeline = pipeline

    async def retrieve(self, query: str, doc_id: str, *, top_k: int) -> list[RetrievedChunk]:
        # The pipeline reads top_k from its config; the argument keeps the
        # Retriever contract identical to the lexical smoke implementation.
        return await self.pipeline.retrieve_chunks(query, doc_id, user_id="eval")

    async def all_chunks(self, doc_id: str) -> list[RetrievedChunk]:
        return await self.pipeline.vector_store.get_document_chunks(doc_id, user_id="eval")


async def _answer(
    case: GoldenCase, retrieved: list[RetrievedChunk], pipeline: RAGPipeline,
) -> tuple[str, list[RetrievedChunk], Optional[float]]:
    sources = retrieved if is_document_overview(case.query) else pipeline.select_context_chunks(retrieved)
    if sources:
        first_token = None
        parts: list[str] = []
        async for delta in pipeline.stream_answer(
            case.query, case.doc, case.language, user_id="eval",
            retrieved_chunks_override=sources,
        ):
            if delta:
                if first_token is None:
                    first_token = perf_counter()
                parts.append(delta)
        return "".join(parts), sources, first_token

    fallback = (
        "Không tìm thấy đoạn văn nào trong tài liệu đủ liên quan với câu hỏi "
        "đang hỏi. Hãy thử hỏi cụ thể hơn hoặc yêu cầu tóm tắt tài liệu."
        if case.language == "vi" else
        "No sufficiently relevant passages were retrieved from this document. "
        "Try a more specific question or request a document summary."
    )
    return fallback, [], perf_counter()


async def run_cases(
    dataset: GoldenSet, cases: Iterable[GoldenCase], retriever, pipeline: RAGPipeline,
    config: AppConfig, *, plan: str, metered: bool, budget_micros: Optional[int] = None,
    starting_cost_micros: int = 0,
) -> tuple[list[CaseResult], dict]:
    results: list[CaseResult] = []
    spent = starting_cost_micros
    for case in cases:
        case_usage = EvalUsage() if metered else None
        pipeline.usage = case_usage
        overview = is_document_overview(case.query)
        route = choose_route(config, plan=plan, query=case.query, overview=overview)
        pipeline.budget = budget_for(config, route)
        started = perf_counter()
        retrieved = await retriever.retrieve(case.query, case.doc, top_k=config.retrieval_top_k)
        answer, sources, first_token_at = await _answer(case, retrieved, pipeline)
        latency_ms = (perf_counter() - started) * 1000
        first_token_ms = (
            round((first_token_at - started) * 1000, 2) if first_token_at is not None else None
        )
        calls = case_usage.calls if case_usage else []
        known, unknown = usage_totals(calls)
        result = score_case(
            case, retrieved, sources, answer, latency_ms=round(latency_ms, 2),
            first_token_ms=first_token_ms, cost_micros=known if not unknown else None,
            cost_known_micros=known, unknown_cost_calls=unknown, provider_calls=len(calls),
        )
        results.append(result)
        spent += known
        if budget_micros is not None and spent > budget_micros:
            raise EvaluationError(
                f"Evaluation budget exceeded: spent at least {spent} micro-USD "
                f"of {budget_micros}."
            )
    return results, {"spent_micros": spent, "limit_micros": budget_micros}


def _artifact(
    mode: str, dataset: GoldenSet, dataset_path: str, config: AppConfig, plan: str,
    results: list[CaseResult], duration_ms: float, budget: dict,
    index: Optional[dict] = None,
) -> dict:
    return {
        "version": 1,
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": round(duration_ms, 2),
        "dataset": {"path": str(dataset_path), "sha256": dataset_sha256(dataset)},
        "settings": {
            "top_k": config.retrieval_top_k,
            "plan": plan,
            "model": config.model,
            "routing_enabled": config.model_routing_enabled,
            "request_cost_cap_micros": config.request_cost_cap_micros,
        },
        "index": index or {},
        "budget": budget,
        "summary": summarize(results),
        "cases": [result.to_dict() for result in results],
    }


def run_smoke(
    dataset: GoldenSet, dataset_path: str | Path, *, top_k: int = 3, plan: str = "pro",
) -> dict:
    started = perf_counter()
    config = AppConfig(
        model="extractive-smoke", temperature=0, max_tokens=2048,
        retrieval_top_k=top_k, min_relevance_score=0.0,
        request_cost_cap_micros=0,
    )

    async def execute():
        pipeline = RAGPipeline(chat_provider=ExtractiveProvider(), config=config)
        try:
            results, budget = await run_cases(
                dataset, dataset.cases, LexicalRetriever(dataset.documents), pipeline,
                config, plan=plan, metered=False,
            )
        finally:
            await pipeline.shutdown()
        return results, budget

    results, budget = asyncio.run(execute())
    return _artifact(
        "smoke", dataset, str(dataset_path), config, plan, results,
        (perf_counter() - started) * 1000, budget,
    )


def run_live(
    dataset: GoldenSet, dataset_path: str | Path, config: AppConfig, *,
    top_k: int = 3, plan: str = "pro", budget_micros: Optional[int],
    request_cap_micros: Optional[int] = None,
) -> dict:
    if not budget_micros or budget_micros <= 0:
        raise EvaluationError("Live evaluation requires a positive --budget-micros cap.")
    config = replace(config, retrieval_top_k=top_k)
    if request_cap_micros is not None:
        config = replace(config, request_cost_cap_micros=request_cap_micros)
    config.require_openrouter(embeddings=True)
    route_model = choose_route(config, plan=plan, query="", overview=False).model
    started = perf_counter()

    async def execute():
        provider = create_chat_provider(config, model=route_model)
        store = InMemoryVectorStore(config)
        pipeline = RAGPipeline(
            chat_provider=provider, vector_store=store, config=config, model=route_model,
        )
        try:
            await store.connect()
            embedder = await run_in_threadpool(get_embedder, config=config)
            pipeline.embedder = embedder
            index_usage = EvalUsage()
            chunks = await build_vector_index(store, dataset.documents, embedder, index_usage)
            index_known, index_unknown = usage_totals(index_usage.calls)
            if index_known > budget_micros:
                raise EvaluationError(
                    f"Evaluation budget exceeded during indexing: {index_known} micro-USD."
                )
            results, budget = await run_cases(
                dataset, dataset.cases, PipelineRetriever(pipeline), pipeline, config,
                plan=plan, metered=True, budget_micros=budget_micros,
                starting_cost_micros=index_known,
            )
            index = {
                "chunks": chunks,
                "cost_known_micros": index_known,
                "unknown_cost_calls": index_unknown,
            }
            return results, budget, index
        finally:
            await pipeline.shutdown()

    results, budget, index = asyncio.run(execute())
    return _artifact(
        "live", dataset, str(dataset_path), config, plan, results,
        (perf_counter() - started) * 1000, budget, index,
    )


def resolve_dataset(path: str | Path) -> tuple[GoldenSet, Path]:
    from evals.dataset import load

    resolved = Path(path).resolve()
    return load(resolved), resolved


def write_artifact(artifact: dict, output: str | Path) -> Path:
    import json

    resolved = Path(output)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return resolved
