"""RAG pipeline attributes every metered provider call to one usage collector."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ai.rag_pipeline import RAGPipeline
from app.services.provider_calls import UsageAttribution, UsageCollector
from app.storage.base import RetrievedChunk, VectorStore


class FakeEmbedder:
    dimension = 2

    def __init__(self):
        self.calls = 0

    def embed_documents(self, texts, *, usage=None):
        self.calls += 1
        if usage is not None:
            usage.apply_usage({"prompt_tokens": len(texts), "cost": "0.000002"})
        return [[0.1, 0.2] for _ in texts]


class FakeProvider:
    def __init__(self, *, summary_size=20):
        self.calls = []
        self.summary_size = summary_size

    async def generate_with_context(self, **kwargs):
        usage = kwargs.get("usage")
        if usage is not None:
            usage.apply_usage({"prompt_tokens": 5, "completion_tokens": 2, "cost": "0.000001"})
        self.calls.append(kwargs)
        return "condensed " + "s" * self.summary_size

    async def stream_with_context(self, **kwargs):
        usage = kwargs.get("usage")
        if usage is not None:
            usage.apply_usage({"prompt_tokens": 7, "completion_tokens": 3, "cost": "0.000003"})
        self.calls.append(kwargs)
        yield "answer"


def collector(*, enabled=True):
    return UsageCollector(
        UsageAttribution(), config=SimpleNamespace(
            database_url="postgresql://example.test/doctrace" if enabled else None,
            openrouter_api_key=None,
        ),
    )


def config(**overrides):
    values = {
        "model": "chat-model", "embedding_model": "embedding-model",
        "retrieval_top_k": 8, "min_relevance_score": 0.3,
        "context_max_chars": 600, "temperature": 0,
        "max_tokens": 200, "summary_max_calls": 20,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def store(chunks):
    fake = AsyncMock(spec=VectorStore)
    fake.search_chunks.return_value = chunks
    fake.get_document_chunks.return_value = chunks
    return fake


async def test_ordinary_chat_records_query_embedding_and_answer():
    usage = collector()
    chunks = [RetrievedChunk("c1", "doc", "Twelve days.", 2, "policy.pdf", 0.9)]
    provider = FakeProvider()
    pipeline = RAGPipeline(
        chat_provider=provider, vector_store=store(chunks),
        config=config(), usage=usage,
    )
    pipeline.embedder = FakeEmbedder()

    await pipeline.retrieve_chunks("How many days?", user_id="user")
    answer = "".join([
        part async for part in pipeline.stream_answer(
            "How many days?", user_id="user",
            retrieved_chunks_override=chunks,
        )
    ])

    assert answer == "answer"
    assert [call.kind for call in usage.calls] == ["query_embedding", "answer"]
    assert usage.calls[0].model == "embedding-model"
    assert usage.calls[1].model == "chat-model"
    assert usage.calls[0].cost_micros == 2
    assert usage.calls[1].cost_micros == 3


async def test_document_overview_records_each_summary_and_the_answer():
    usage = collector()
    chunks = [
        RetrievedChunk("c1", "doc", "x" * 700 + " END-1", 1, "long.pdf", None),
        RetrievedChunk("c2", "doc", "y" * 700 + " END-2", 2, "long.pdf", None),
    ]
    provider = FakeProvider()
    pipeline = RAGPipeline(
        chat_provider=provider, vector_store=store(chunks),
        config=config(), usage=usage,
    )

    retrieved = await pipeline.retrieve_chunks("Summarize this PDF", "doc", user_id="user")
    _ = [part async for part in pipeline.stream_answer(
        "Summarize this PDF", "doc", user_id="user",
        retrieved_chunks_override=retrieved,
    )]

    kinds = [call.kind for call in usage.calls]
    assert kinds == ["summary", "summary", "summary", "summary", "answer"]
    assert all(call.cost_micros == 1 for call in usage.calls[:-1])
    assert usage.calls[-1].cost_micros == 3


async def test_summary_cap_midway_keeps_completed_calls_for_flushing():
    usage = collector()
    # Four sections just over half the context budget cannot pair up, so the
    # first round needs four calls. Short summaries then merge into two
    # contexts, which would need two more calls — beyond the cap.
    chunks = [
        RetrievedChunk(f"c{i}", "doc", "x" * 350, i, "long.pdf", None)
        for i in range(1, 5)
    ]
    provider = FakeProvider(summary_size=288)
    pipeline = RAGPipeline(
        chat_provider=provider, vector_store=store(chunks),
        config=config(summary_max_calls=5), usage=usage,
    )

    with pytest.raises(RuntimeError, match="too many provider calls"):
        _ = [part async for part in pipeline.stream_answer(
            "Summarize this PDF", "doc", user_id="user",
            retrieved_chunks_override=chunks,
        )]

    assert [call.kind for call in usage.calls] == ["summary"] * 4
    assert all(call.cost_micros == 1 for call in usage.calls)
    assert not any(call.kind == "answer" for call in usage.calls)


async def test_summary_cap_rejects_before_any_paid_call():
    usage = collector()
    chunks = [
        RetrievedChunk("c1", "doc", "x" * 1200, 1, "long.pdf", None),
        RetrievedChunk("c2", "doc", "y" * 1200, 2, "long.pdf", None),
    ]
    provider = FakeProvider()
    pipeline = RAGPipeline(
        chat_provider=provider, vector_store=store(chunks),
        config=config(summary_max_calls=2), usage=usage,
    )

    with pytest.raises(RuntimeError, match="too many provider calls"):
        _ = [part async for part in pipeline.stream_answer(
            "Summarize this PDF", "doc", user_id="user",
            retrieved_chunks_override=chunks,
        )]

    assert usage.calls == []
    assert provider.calls == []


async def test_disabled_usage_starts_no_calls_and_passes_no_usage_kwarg():
    usage = collector(enabled=False)
    chunks = [RetrievedChunk("c1", "doc", "Twelve days.", 2, "policy.pdf", 0.9)]
    provider = FakeProvider()
    pipeline = RAGPipeline(
        chat_provider=provider, vector_store=store(chunks),
        config=config(), usage=usage,
    )
    pipeline.embedder = FakeEmbedder()

    await pipeline.retrieve_chunks("How many days?", user_id="user")
    _ = [part async for part in pipeline.stream_answer(
        "How many days?", user_id="user",
        retrieved_chunks_override=chunks,
    )]

    assert usage.calls == []
    assert "usage" not in provider.calls[0]
    assert usage.start("answer", "model") is None
