"""Provider usage capture, cost normalization and streaming edge cases."""
import asyncio
from types import SimpleNamespace

import pytest

from app.providers.embeddings import OpenRouterEmbedder
from app.providers.openrouter import OpenRouterChatProvider, fetch_generation
from app.providers.usage import ProviderCall, update_from_chunk


def _client(*, chunks=None, response=None):
    calls = []

    async def create(**params):
        calls.append(params)
        if response is not None:
            return response

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()

    fake = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )
    return fake, calls


def _chunk(content=None, *, chunk_id="gen-1", usage=None, choices=True):
    if choices:
        return SimpleNamespace(
            id=chunk_id,
            choices=[SimpleNamespace(
                delta=SimpleNamespace(content=content),
                finish_reason=None,
            )],
            usage=usage,
        )
    return SimpleNamespace(id=chunk_id, choices=[], usage=usage)


def _usage(**overrides):
    values = {
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "total_tokens": 14,
        "cost": 0.000123,
        "prompt_tokens_details": SimpleNamespace(cached_tokens=3),
        "completion_tokens_details": SimpleNamespace(reasoning_tokens=2),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_stream_captures_final_usage_chunk_with_empty_choices():
    provider = OpenRouterChatProvider(
        api_key="key", model="test-model", base_url="https://example.test/v1", timeout=5,
    )
    fake, calls = _client(chunks=[
        _chunk("Hello "),
        _chunk("world."),
        _chunk(None, choices=False, usage=_usage()),
    ])
    provider._get_client = lambda: fake
    call = ProviderCall(kind="answer", model="test-model")

    text = "".join([
        piece async for piece in provider.stream_completion(
            [{"role": "user", "content": "hi"}], usage=call,
        )
    ])

    assert text == "Hello world."
    assert calls[0]["stream_options"] == {"include_usage": True}
    assert call.generation_id == "gen-1"
    assert call.prompt_tokens == 10
    assert call.completion_tokens == 4
    assert call.cached_tokens == 3
    assert call.reasoning_tokens == 2
    assert call.cost_micros == 123
    assert call.cost_status == "reported"
    assert call.status == "ok"
    assert call.latency_ms is not None


@pytest.mark.asyncio
async def test_missing_cost_is_unknown_and_never_zero():
    provider = OpenRouterChatProvider(
        api_key="key", model="test-model", base_url="https://example.test/v1", timeout=5,
    )
    usage = _usage(cost=None, prompt_tokens_details=None, completion_tokens_details=None)
    fake, _ = _client(chunks=[_chunk("answer"), _chunk(None, choices=False, usage=usage)])
    provider._get_client = lambda: fake
    call = ProviderCall(kind="answer", model="test-model")

    _ = [piece async for piece in provider.stream_completion(
        [{"role": "user", "content": "hi"}], usage=call,
    )]

    assert call.prompt_tokens == 10
    assert call.cost_usd is None
    assert call.cost_micros is None
    assert call.cost_status == "unknown"


@pytest.mark.asyncio
async def test_non_streaming_response_captures_generation_and_usage():
    provider = OpenRouterChatProvider(
        api_key="key", model="test-model", base_url="https://example.test/v1", timeout=5,
    )
    response = SimpleNamespace(
        id="gen-2",
        choices=[SimpleNamespace(message=SimpleNamespace(content="Done"))],
        usage=_usage(cost="0.0000015"),
    )
    fake, _ = _client(response=response)
    provider._get_client = lambda: fake
    call = ProviderCall(kind="answer", model="test-model")

    assert await provider.generate_completion(
        [{"role": "user", "content": "hi"}], usage=call,
    ) == "Done"
    assert call.generation_id == "gen-2"
    # Decimal micro-USD rounding, never float arithmetic.
    assert call.cost_micros == 2
    assert call.cost_status == "reported"
    assert call.latency_ms is not None


@pytest.mark.asyncio
async def test_non_streaming_cancellation_marks_usage_cancelled():
    provider = OpenRouterChatProvider(
        api_key="key", model="test-model", base_url="https://example.test/v1", timeout=5,
    )

    async def create(**params):
        raise asyncio.CancelledError()

    provider._get_client = lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )
    call = ProviderCall(kind="summary", model="test-model")

    with pytest.raises(asyncio.CancelledError):
        await provider.generate_completion(
            [{"role": "user", "content": "hi"}], usage=call,
        )

    assert call.status == "error"
    assert call.error_code == "cancelled"
    assert call.cost_micros is None
    assert call.latency_ms is not None


async def test_stream_cancellation_marks_the_call_and_closes_upstream():
    provider = OpenRouterChatProvider(
        api_key="key", model="test-model", base_url="https://example.test/v1", timeout=5,
    )
    closed = []

    async def endless_stream():
        try:
            yield _chunk("partial")
            yield _chunk("more")
        finally:
            closed.append(True)

    async def create(**params):
        return endless_stream()

    provider._get_client = lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )
    call = ProviderCall(kind="answer", model="test-model")
    stream = provider.stream_completion(
        [{"role": "user", "content": "hi"}], usage=call,
    )

    assert await anext(stream) == "partial"
    await stream.aclose()

    assert closed == [True]
    assert call.status == "error"
    assert call.error_code == "cancelled"
    assert call.cost_status == "unknown"
    assert call.latency_ms is not None


async def test_stream_error_marks_call_failed_and_still_releases_the_stream():
    provider = OpenRouterChatProvider(
        api_key="key", model="test-model", base_url="https://example.test/v1", timeout=5,
    )
    closed = []

    async def failing_stream():
        try:
            yield _chunk("partial")
            raise ConnectionError("upstream reset")
        finally:
            closed.append(True)

    calls = []

    async def create(**params):
        calls.append(params)
        return failing_stream()

    provider._get_client = lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )
    call = ProviderCall(kind="answer", model="test-model")

    with pytest.raises(RuntimeError, match="streaming error"):
        _ = [piece async for piece in provider.stream_completion(
            [{"role": "user", "content": "hi"}], usage=call,
        )]

    assert closed == [True]
    assert call.status == "error"
    assert call.error_code == "provider_error"
    assert call.cost_micros is None
    assert call.cost_status == "unknown"


def test_cumulative_usage_chunks_replace_instead_of_double_counting():
    call = ProviderCall(kind="answer", model="test-model")

    update_from_chunk(call, _chunk("first", usage=_usage(prompt_tokens=10, completion_tokens=2)))
    update_from_chunk(call, _chunk(None, choices=False, usage=_usage(prompt_tokens=10, completion_tokens=6)))

    assert call.prompt_tokens == 10
    assert call.completion_tokens == 6
    assert call.cost_micros == 123


def test_replacement_usage_without_cost_never_keeps_a_stale_cost():
    call = ProviderCall(kind="answer", model="test-model")

    update_from_chunk(call, _chunk("partial", usage=_usage()))
    update_from_chunk(call, _chunk(
        None, choices=False,
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=6),
    ))

    assert call.prompt_tokens == 10
    assert call.cost_usd is None
    assert call.cost_micros is None
    assert call.cost_status == "unknown"


def test_malformed_cost_is_unknown_and_never_crashes_usage_capture():
    call = ProviderCall(kind="answer", model="test-model")

    call.apply_usage({"prompt_tokens": 3, "cost": "not-a-number"}, accumulate=False)
    assert call.prompt_tokens == 3
    assert call.cost_usd is None
    assert call.cost_status == "unknown"

    call.apply_generation({"total_cost": "still-not-a-number"})
    assert call.cost_usd is None
    assert call.cost_status == "unknown"


@pytest.mark.parametrize("cost", ["NaN", "Infinity", "-Infinity", "-0.1"])
def test_non_finite_or_negative_cost_is_never_stored(cost):
    call = ProviderCall(kind="answer", model="test-model")

    call.apply_usage({"cost": cost}, accumulate=False)
    assert call.cost_usd is None
    assert call.cost_micros is None
    assert call.cost_status == "unknown"

    call.apply_generation({"total_cost": cost})
    assert call.cost_usd is None
    assert call.cost_micros is None
    assert call.cost_status == "unknown"


def _embedder(batch_size, responses):
    embedder = object.__new__(OpenRouterEmbedder)
    embedder._model = "test-embedding"
    embedder._batch_size = batch_size
    embedder._dim = 2
    calls = []

    def create(**params):
        calls.append(params)
        result = responses[len(calls) - 1]
        if isinstance(result, Exception):
            raise result
        return result

    embedder._client = SimpleNamespace(
        embeddings=SimpleNamespace(create=create),
    )
    return embedder, calls


def _embedding_response(indexes, *, cost="0.000001", tokens=2, usage=True):
    return SimpleNamespace(
        data=[
            SimpleNamespace(index=index, embedding=[float(index), 1.0])
            for index in indexes
        ],
        usage=(
            SimpleNamespace(prompt_tokens=tokens, total_tokens=tokens, cost=cost)
            if usage else None
        ),
    )


def test_embedding_batches_aggregate_tokens_and_cost_into_one_call():
    embedder, calls = _embedder(2, [
        _embedding_response([0, 1]),
        _embedding_response([0, 1]),
        _embedding_response([0]),
    ])
    call = ProviderCall(kind="index_embedding", model="test-embedding")

    vectors = embedder.embed_documents(["a", "b", "c", "d", "e"], usage=call)

    assert [params["input"] for params in calls] == [["a", "b"], ["c", "d"], ["e"]]
    assert len(vectors) == 5
    assert call.prompt_tokens == 6
    assert call.cost_micros == 3
    assert call.cost_status == "reported"
    assert call.latency_ms is not None
    # Embedding batches are not chat generations and must not be reconciled.
    assert call.generation_id is None


def test_embedding_aggregate_is_unknown_if_any_batch_omits_cost():
    embedder, _ = _embedder(2, [
        _embedding_response([0, 1]),
        _embedding_response([0], cost=None),
    ])
    call = ProviderCall(kind="index_embedding", model="test-embedding")

    embedder.embed_documents(["a", "b", "c"], usage=call)

    assert call.prompt_tokens == 4  # Tokens are still exact.
    assert call.cost_usd is None
    assert call.cost_micros is None
    assert call.cost_status == "unknown"


def test_embedding_aggregate_is_unknown_if_a_batch_has_no_usage_object():
    embedder, _ = _embedder(2, [
        _embedding_response([0, 1]),
        _embedding_response([0], usage=False),
    ])
    call = ProviderCall(kind="index_embedding", model="test-embedding")

    embedder.embed_documents(["a", "b", "c"], usage=call)

    # Tokens from the reporting batch remain exact; the missing batch is
    # absent from the total, so the cost must never look complete.
    assert call.prompt_tokens == 2
    assert call.cost_usd is None
    assert call.cost_micros is None
    assert call.cost_status == "unknown"


def test_embedding_failure_marks_the_call_but_keeps_earlier_usage():
    embedder, _ = _embedder(2, [
        _embedding_response([0, 1]),
        ConnectionError("upstream reset"),
    ])
    call = ProviderCall(kind="index_embedding", model="test-embedding")

    with pytest.raises(ConnectionError):
        embedder.embed_documents(["a", "b", "c"], usage=call)

    assert call.status == "error"
    assert call.error_code == "provider_error"
    assert call.prompt_tokens == 2
    assert call.cost_micros == 1
    assert call.latency_ms is not None


def test_empty_embedding_input_never_calls_the_provider():
    embedder, calls = _embedder(2, [])
    call = ProviderCall(kind="index_embedding", model="test-embedding")

    assert embedder.embed_documents([], usage=call) == []
    assert calls == []
    assert call.cost_micros is None
    assert call.cost_status == "unknown"


async def test_chat_provider_disables_sdk_retries():
    provider = OpenRouterChatProvider(
        api_key="key", model="test-model", base_url="https://example.test/v1", timeout=5,
    )
    try:
        assert provider._get_client().max_retries == 0
    finally:
        await provider.close()


def test_embedder_disables_sdk_retries(monkeypatch):
    import openai

    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.embeddings = SimpleNamespace(
                create=lambda **params: SimpleNamespace(
                    data=[SimpleNamespace(index=0, embedding=[0.1, 0.2])],
                ),
            )

        def close(self):
            pass

    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    OpenRouterEmbedder(
        model="test-embedding", api_key="key",
        base_url="https://example.test/v1", timeout=5, batch_size=2,
    )

    assert captured["max_retries"] == 0


def _generation_client(monkeypatch, response):
    from app.providers import openrouter

    requests = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None, headers=None):
            requests.append({"url": url, "params": params, "headers": headers})
            return response

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", FakeClient)
    return requests


async def test_fetch_generation_reads_exact_cost(monkeypatch):
    response = SimpleNamespace(
        status_code=200,
        json=lambda: {"data": {"id": "gen-1", "total_cost": 0.00005}},
    )
    requests = _generation_client(monkeypatch, response)
    config = SimpleNamespace(
        upstream_timeout_seconds=60, openrouter_base_url="https://example.test/v1",
        openrouter_api_key="key",
    )

    data = await fetch_generation(config, "gen-1")

    assert data == {"id": "gen-1", "total_cost": 0.00005}
    assert requests[0]["url"] == "https://example.test/v1/generation"
    assert requests[0]["params"] == {"id": "gen-1"}
    assert requests[0]["headers"] == {"Authorization": "Bearer key"}


async def test_fetch_generation_failure_is_best_effort(monkeypatch):
    response = SimpleNamespace(status_code=404, json=lambda: {})
    _generation_client(monkeypatch, response)
    config = SimpleNamespace(
        upstream_timeout_seconds=60, openrouter_base_url="https://example.test/v1",
        openrouter_api_key="key",
    )

    assert await fetch_generation(config, "missing") is None

    class BrokenClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            raise ConnectionError("down")

        async def __aexit__(self, *args):
            return False

    from app.providers import openrouter
    monkeypatch.setattr(openrouter.httpx, "AsyncClient", BrokenClient)
    assert await fetch_generation(config, "broken") is None
