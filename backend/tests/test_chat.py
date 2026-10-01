"""
Chat API contracts through the real RAG pipeline with external services mocked.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.ai import rag_pipeline
from app.providers import factory as provider_factory
from app.providers.openrouter import OpenRouterChatProvider
from app.storage import factory as vector_store_factory
from app.storage.base import RetrievedChunk, VectorStore


@pytest.fixture
def chat_dependencies(monkeypatch):
    config = SimpleNamespace(
        model="test-model", vector_store_type="milvus", retrieval_top_k=8,
        min_relevance_score=0.32, context_max_chars=6000, temperature=0.7, max_tokens=4096,
    )
    monkeypatch.setattr(rag_pipeline, "get_config", lambda: config)
    embedder = MagicMock()
    embedder.embed_documents.return_value = [[0.1, 0.2, 0.3]]
    monkeypatch.setattr(rag_pipeline, "get_embedder", lambda: embedder)
    vector_store = AsyncMock(spec=VectorStore)
    vector_store.search_chunks.return_value = [
        RetrievedChunk("chunk-1", "test-doc-id", "Twelve days of annual leave.", 2, "policy.pdf", 0.9)
    ]
    monkeypatch.setattr(vector_store_factory, "create_vector_store", lambda **kwargs: vector_store)

    async def completion_stream():
        for text in ["Twelve ", "days."]:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])

    create_completion = AsyncMock(return_value=completion_stream())
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_completion)))
    provider = OpenRouterChatProvider(api_key="test-key", model="test-model")
    monkeypatch.setattr(provider, "_get_client", lambda: client)
    monkeypatch.setattr(provider_factory, "create_chat_provider", lambda **kwargs: provider)
    return SimpleNamespace(
        embedder=embedder, vector_store=vector_store, create_completion=create_completion,
    )


def parse_sse_events(response):
    events = []
    for block in response.text.strip().split("\n\n"):
        event_line, data_line = block.split("\n", 1)
        events.append((event_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: "))))
    return events


def test_chat_422_when_query_empty(client: TestClient) -> None:
    """422 (Pydantic validation) when body has empty query."""
    response = client.post(
        "/api/chat",
        json={"query": "", "doc_id": "some-doc-id"},
    )
    assert response.status_code == 422


def test_chat_422_when_doc_id_missing(client: TestClient) -> None:
    """422 (Pydantic validation) when doc_id is missing."""
    response = client.post(
        "/api/chat",
        json={"query": "Nội dung chính?"},
    )
    assert response.status_code == 422


def test_chat_sse_stream(chat_dependencies, client: TestClient) -> None:
    """Retrieval feeds context into the chat provider and preserves the SSE contract."""
    deps = chat_dependencies
    response = client.post(
        "/api/chat",
        json={"query": "How much leave?", "doc_id": "test-doc-id", "language": "en"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert parse_sse_events(response) == [
        ("sources", [{"page": 2, "source": "policy.pdf", "score": 0.9}]),
        ("token", "Twelve "),
        ("token", "days."),
        ("done", "[DONE]"),
    ]
    deps.embedder.embed_documents.assert_called_once_with(["How much leave?"])
    deps.vector_store.search_chunks.assert_awaited_once_with(
        query_vector=[0.1, 0.2, 0.3], doc_id="test-doc-id", top_k=8, min_score=0.32,
        user_id="00000000-0000-0000-0000-000000000001",
    )
    messages = deps.create_completion.call_args.kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert "Twelve days of annual leave." in messages[1]["content"]
    assert "How much leave?" in messages[1]["content"]
    deps.vector_store.connect.assert_awaited_once()
    deps.vector_store.disconnect.assert_awaited_once()


def test_chat_sse_error_path(chat_dependencies, client: TestClient) -> None:
    """Retrieval failures emit error + done and release the vector store connection."""
    deps = chat_dependencies
    deps.vector_store.search_chunks.side_effect = RuntimeError("fail")
    response = client.post(
        "/api/chat",
        json={"query": "Anything", "doc_id": "nonexistent-doc"},
    )
    assert response.status_code == 200
    assert parse_sse_events(response) == [
        ("error", {"message": "Chat service unavailable. Please try again."}), ("done", "[DONE]"),
    ]
    deps.create_completion.assert_not_awaited()
    deps.vector_store.disconnect.assert_awaited_once()


def test_chat_cannot_override_owner_in_payload(client):
    response = client.post("/api/chat", json={"query": "q", "doc_id": "doc", "user_id": "someone-else"})
    assert response.status_code == 422


def test_other_users_document_produces_no_context(chat_dependencies, client):
    from app.core.auth import require_supabase_user
    from app.main import app

    async def second_user():
        return {"id": "user-b"}

    app.dependency_overrides[require_supabase_user] = second_user
    deps = chat_dependencies

    async def owner_scoped_search(**kwargs):
        assert kwargs["user_id"] == "user-b"
        # The document belongs to A; the owner-scoped store returns no rows.
        return []

    deps.vector_store.search_chunks.side_effect = owner_scoped_search
    response = client.post("/api/chat", json={"query": "secret?", "doc_id": "user-a-document"})
    assert parse_sse_events(response)[0] == ("sources", [])
    deps.create_completion.assert_not_awaited()


def test_generation_failure_is_an_error_event(chat_dependencies, client):
    chat_dependencies.create_completion.side_effect = RuntimeError("private upstream details")
    events = parse_sse_events(client.post("/api/chat", json={"query": "q", "doc_id": "doc"}))
    assert [event[0] for event in events] == ["sources", "error", "done"]
    assert "private upstream details" not in str(events)
    chat_dependencies.vector_store.disconnect.assert_awaited_once()


def test_initialization_failure_releases_connection(chat_dependencies, client):
    chat_dependencies.vector_store.connect.side_effect = RuntimeError("cannot connect")
    response = client.post("/api/chat", json={"query": "q", "doc_id": "doc"})
    assert [event[0] for event in parse_sse_events(response)] == ["error", "done"]
    chat_dependencies.vector_store.disconnect.assert_awaited_once()


def test_provider_midstream_error_is_not_a_success(chat_dependencies, client):
    async def failed_stream():
        yield SimpleNamespace(choices=[], error={"message": "quota exceeded"})

    chat_dependencies.create_completion.return_value = failed_stream()
    response = client.post("/api/chat", json={"query": "q", "doc_id": "doc"})
    assert [event[0] for event in parse_sse_events(response)] == ["sources", "error", "done"]


@pytest.mark.parametrize("vectors", [[], [[]]])
def test_invalid_query_embedding_is_an_error_not_empty_retrieval(chat_dependencies, client, vectors):
    chat_dependencies.embedder.embed_documents.return_value = vectors
    response = client.post("/api/chat", json={"query": "q", "doc_id": "doc"})
    assert [event[0] for event in parse_sse_events(response)] == ["error", "done"]
    chat_dependencies.vector_store.search_chunks.assert_not_awaited()
    chat_dependencies.vector_store.disconnect.assert_awaited_once()


def test_chat_without_sources_skips_completion(chat_dependencies, client: TestClient) -> None:
    deps = chat_dependencies
    deps.vector_store.search_chunks.return_value = []
    response = client.post(
        "/api/chat",
        json={"query": "How much leave?", "doc_id": "test-doc-id", "language": "en"},
    )
    events = parse_sse_events(response)
    assert events[0] == ("sources", [])
    assert events[1][0] == "token"
    assert "No sufficiently relevant passages" in events[1][1]
    assert events[2] == ("done", "[DONE]")
    deps.create_completion.assert_not_awaited()
    deps.vector_store.disconnect.assert_awaited_once()
