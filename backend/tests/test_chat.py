"""
Chat API contracts through the real RAG pipeline with external services mocked.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.ai import rag_pipeline
from app.main import app
from app.providers import factory as provider_factory
from app.providers.openrouter import OpenRouterChatProvider
from app.services.rate_limiter import get_rate_limiter
from app.storage import factory as vector_store_factory
from app.storage.base import RetrievedChunk, VectorStore

OWNER = "00000000-0000-0000-0000-000000000001"
WORKSPACE = "00000000-0000-0000-0000-0000000000ab"
REQUEST_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def chat_dependencies(monkeypatch):
    config = SimpleNamespace(
        model="test-model", retrieval_top_k=8,
        min_relevance_score=0.32, context_max_chars=6000, temperature=0.7, max_tokens=4096,
    )
    monkeypatch.setattr(rag_pipeline, "get_config", lambda: config)
    embedder = MagicMock()
    embedder.embed_documents.return_value = [[0.1, 0.2, 0.3]]
    monkeypatch.setattr(rag_pipeline, "get_embedder", lambda **kwargs: embedder)
    vector_store = AsyncMock(spec=VectorStore)
    vector_store.search_chunks.return_value = [
        RetrievedChunk("chunk-1", "test-doc-id", "Twelve days of annual leave.", 2, "policy.pdf", 0.9)
    ]
    vector_store.get_document_chunks.return_value = [
        RetrievedChunk("chunk-1", "test-doc-id", "Twelve days of annual leave.", 2, "policy.pdf", None)
    ]
    monkeypatch.setattr(vector_store_factory, "create_vector_store", lambda **kwargs: vector_store)

    async def completion_stream():
        for text in ["Twelve ", "days."]:
            yield SimpleNamespace(
                id="gen-answer",
                choices=[SimpleNamespace(delta=SimpleNamespace(content=text))],
                usage=None,
            )
        # OpenRouter sends final usage on a chunk with empty choices.
        yield SimpleNamespace(
            id="gen-answer",
            choices=[],
            usage=SimpleNamespace(
                prompt_tokens=12, completion_tokens=2, total_tokens=14,
                cost=0.000045,
                prompt_tokens_details=SimpleNamespace(cached_tokens=1),
                completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
            ),
        )

    create_completion = AsyncMock(return_value=completion_stream())
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_completion)))
    provider = OpenRouterChatProvider(api_key="test-key", model="test-model", base_url="https://example.test/v1", timeout=10)
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
        ("sources", [{"citation_id": 1, "chunk_id": "chunk-1", "doc_id": "test-doc-id", "page": 2, "source": "policy.pdf", "score": 0.9}]),
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


def test_chat_resolves_generation_but_citations_keep_public_document_id(chat_dependencies, client, repository):
    repository.get.side_effect = None
    repository.get.return_value = {"status": "ready", "active_index_id": "private-generation"}
    events = parse_sse_events(client.post("/api/chat", json={"query": "How much leave?", "doc_id": "public-document"}))
    assert chat_dependencies.vector_store.search_chunks.call_args.kwargs["doc_id"] == "private-generation"
    assert events[0][1][0]["doc_id"] == "public-document"
    assert events[0][1][0]["chunk_id"] == "chunk-1"
    context = chat_dependencies.create_completion.call_args.kwargs["messages"][1]["content"]
    assert "[1] [Trang 2]" in context


def test_chat_cannot_override_owner_in_payload(client):
    response = client.post("/api/chat", json={"query": "q", "doc_id": "doc", "user_id": "someone-else"})
    assert response.status_code == 422


def test_other_users_document_is_not_found_before_retrieval(chat_dependencies, client, repository):
    from fastapi import HTTPException

    from app.core.workspace import require_workspace
    from app.main import app
    from app.services.workspaces import WorkspaceContext

    async def second_user():
        return WorkspaceContext(
            workspace_id="00000000-0000-0000-0000-0000000000cd", user_id="user-b",
            role="owner", plan="free", kind="personal", name="Khác",
        )

    app.dependency_overrides[require_workspace] = second_user
    repository.get.side_effect = HTTPException(404, "Not found")
    deps = chat_dependencies
    response = client.post("/api/chat", json={"query": "secret?", "doc_id": "user-a-document"})
    assert response.status_code == 404
    repository.get.assert_awaited_once_with(
        "00000000-0000-0000-0000-0000000000cd", "user-b", "user-a-document",
    )
    deps.vector_store.search_chunks.assert_not_awaited()
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


@pytest.mark.parametrize("query", [
    "hãy tóm tắt file pdf này cho tôi", "file này viết về cái gì vậy",
    "Tài liệu này nói về điều gì?", "Nội dung chính của PDF là gì?",
    "tom tat tai lieu nay", "Summarize this PDF", "What is this document about?",
])
def test_document_overview_uses_owned_content_without_embeddings(chat_dependencies, client, monkeypatch, query):
    deps = chat_dependencies
    get_embedder = MagicMock(side_effect=RuntimeError("embedding service unavailable"))
    monkeypatch.setattr(rag_pipeline, "get_embedder", get_embedder)
    response = client.post("/api/chat", json={"query": query, "doc_id": "test-doc-id"})
    events = parse_sse_events(response)
    assert [event[0] for event in events] == ["sources", "token", "token", "done"]
    assert events[0][1] == [{"citation_id": 1, "chunk_id": "chunk-1", "doc_id": "test-doc-id", "page": 2, "source": "policy.pdf", "score": None}]
    deps.vector_store.get_document_chunks.assert_awaited_once_with(
        "test-doc-id", user_id="00000000-0000-0000-0000-000000000001",
    )
    get_embedder.assert_not_called()
    deps.vector_store.search_chunks.assert_not_awaited()
    assert "Twelve days of annual leave." in deps.create_completion.call_args.kwargs["messages"][1]["content"]
    assert deps.create_completion.call_args.kwargs["extra_body"] == {"reasoning": {"enabled": False}}
    deps.vector_store.disconnect.assert_awaited_once()


def test_summary_of_other_users_document_does_not_generate(chat_dependencies, client):
    deps = chat_dependencies

    async def owned_document(doc_id, *, user_id):
        assert user_id == "00000000-0000-0000-0000-000000000001"
        assert doc_id == "someone-elses-doc"
        return []

    deps.vector_store.get_document_chunks.side_effect = owned_document
    response = client.post("/api/chat", json={"query": "Tóm tắt PDF này", "doc_id": "someone-elses-doc"})
    events = parse_sse_events(response)
    assert events[0] == ("sources", [])
    assert "Không tìm thấy nội dung" in events[1][1]
    assert events[-1] == ("done", "[DONE]")
    deps.create_completion.assert_not_awaited()
    deps.vector_store.search_chunks.assert_not_awaited()


def test_long_summary_covers_all_chunks_including_document_end(chat_dependencies, client):
    deps = chat_dependencies
    deps.vector_store.get_document_chunks.return_value = [
        RetrievedChunk(str(i), "doc", f"SECTION-{i} " + "x" * 4000, i, "long.pdf", None)
        for i in range(3)
    ]

    async def final_stream():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Summary."))])

    async def completion(**params):
        if params.get("stream"):
            return final_stream()
        content = params["messages"][1]["content"]
        section = next(i for i in range(3) if f"SECTION-{i}" in content)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=f"Notes-{section} (trang {section})"))])

    deps.create_completion.side_effect = completion
    events = parse_sse_events(client.post("/api/chat", json={"query": "Tóm tắt tài liệu", "doc_id": "doc"}))
    assert [event[0] for event in events] == ["sources", "token", "done"]
    calls = deps.create_completion.call_args_list
    assert len(calls) == 4
    for call in calls[:-1]:
        assert call.kwargs["extra_body"] == {"reasoning": {"enabled": False}}
        context = call.kwargs["messages"][1]["content"].split("\n\nQuestion:")[0].removeprefix("Context:\n")
        assert len(context) <= 6000
    final_context = calls[-1].kwargs["messages"][1]["content"]
    assert all(f"Notes-{i}" in final_context for i in range(3))
    assert [source["page"] for source in events[0][1]] == [0, 1, 2]
    deps.embedder.embed_documents.assert_not_called()


def test_summary_stage_failure_emits_error_and_cleans_up(chat_dependencies, client):
    deps = chat_dependencies
    deps.vector_store.get_document_chunks.return_value = [
        RetrievedChunk("1", "doc", "x" * 8000, 1, "long.pdf", None),
    ]
    deps.create_completion.side_effect = RuntimeError("upstream failed")
    events = parse_sse_events(client.post("/api/chat", json={"query": "Summarize this PDF", "doc_id": "doc"}))
    assert [event[0] for event in events] == ["sources", "error", "done"]
    deps.vector_store.disconnect.assert_awaited_once()


def test_chat_persists_usage_with_attribution_and_never_streams_it(
    chat_dependencies, client, monkeypatch,
):
    from contextlib import contextmanager

    from app.routers import chat as chat_router
    from app.services import provider_calls

    captured = []

    class Session:
        def execute(self, statement, rows):
            captured.extend(rows)

    @contextmanager
    def scope(config):
        yield Session()

    monkeypatch.setattr(provider_calls, "session_scope", scope)
    monkeypatch.setattr(chat_router, "get_config", lambda: SimpleNamespace(
        database_url="postgresql://example.test/doctrace", openrouter_api_key=None,
    ))

    response = client.post(
        "/api/chat",
        json={"query": "How much leave?", "doc_id": "test-doc-id", "language": "en",
              "request_id": REQUEST_ID},
    )
    events = parse_sse_events(response)

    assert [event[0] for event in events] == ["sources", "token", "token", "done"]
    assert [row["kind"] for row in captured] == ["query_embedding", "answer"]
    answer = captured[1]
    assert answer["prompt_tokens"] == 12
    assert answer["completion_tokens"] == 2
    assert answer["cached_tokens"] == 1
    assert answer["cost_micros"] == 45
    assert answer["cost_status"] == "reported"
    assert answer["workspace_id"] == "00000000-0000-0000-0000-0000000000ab"
    assert answer["user_id"] == "00000000-0000-0000-0000-000000000001"
    assert answer["request_id"] == REQUEST_ID
    # Public documents use non-UUID ids in tests; malformed attribution is dropped.
    assert answer["doc_id"] is None
    assert "cost_micros" not in response.text
    assert "usage" not in response.text


def test_chat_admission_uses_the_client_request_id_and_finalizes_status(
    chat_dependencies, client, quotas,
):
    response = client.post(
        "/api/chat",
        json={"query": "How much leave?", "doc_id": "test-doc-id", "request_id": REQUEST_ID},
    )

    assert response.status_code == 200
    quotas.existing_chat.assert_awaited_once_with(WORKSPACE, OWNER, REQUEST_ID)
    quotas.admit_chat.assert_awaited_once_with(
        WORKSPACE, OWNER, REQUEST_ID, "test-doc-id", "free",
    )
    statuses = [call.args[1] for call in quotas.mark_chat_status.await_args_list]
    assert statuses == ["streaming", "completed"]
    assert quotas.mark_chat_status.await_args_list[-1].args[2] is None


def test_chat_generates_a_unique_request_id_when_the_client_omits_one(
    chat_dependencies, client, quotas,
):
    for _ in range(2):
        assert client.post(
            "/api/chat", json={"query": "q", "doc_id": "test-doc-id"},
        ).status_code == 200

    request_ids = [call.args[2] for call in quotas.admit_chat.await_args_list]
    assert len(request_ids) == 2
    assert len(set(request_ids)) == 2
    assert all(len(value) == 36 for value in request_ids)


@pytest.mark.parametrize(("status", "code"), [
    ("completed", "request_completed"),
    ("admitted", "request_in_progress"),
    ("streaming", "request_in_progress"),
    ("failed", "request_failed"),
    ("interrupted", "request_failed"),
])
def test_duplicate_request_never_spends_rate_limit_or_quota(
    chat_dependencies, client, quotas, rate_limiter, status, code,
):
    quotas.existing_chat.return_value = {
        "status": status,
        "chat_request_id": "00000000-0000-0000-0000-0000000000c1",
        "conversation_id": None,
    }

    response = client.post(
        "/api/chat",
        json={"query": "q", "doc_id": "test-doc-id", "request_id": REQUEST_ID},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == code
    rate_limiter.check.assert_not_awaited()
    quotas.admit_chat.assert_not_awaited()
    chat_dependencies.vector_store.connect.assert_not_awaited()
    chat_dependencies.create_completion.assert_not_awaited()


def test_chat_quota_denial_is_json_before_streaming(
    chat_dependencies, client, quotas,
):
    from app.core.errors import api_error

    quotas.admit_chat.side_effect = api_error(
        429, "quota_exceeded", "Đã hết lượt hỏi trong tháng.",
        metric="chat_questions_month", limit=10, used=10,
        reset_at="2026-11-01T00:00:00Z", retry_after=432060,
        headers={"Retry-After": "432060"},
    )

    response = client.post("/api/chat", json={"query": "q", "doc_id": "test-doc-id"})

    assert response.status_code == 429
    assert response.headers["content-type"] == "application/json"
    assert response.headers["retry-after"] == "432060"
    assert response.json()["detail"] == {
        "code": "quota_exceeded",
        "message": "Đã hết lượt hỏi trong tháng.",
        "metric": "chat_questions_month",
        "limit": 10,
        "used": 10,
        "reset_at": "2026-11-01T00:00:00Z",
        "retry_after": 432060,
    }
    chat_dependencies.vector_store.connect.assert_not_awaited()
    chat_dependencies.create_completion.assert_not_awaited()
    quotas.mark_chat_status.assert_not_awaited()


def test_chat_marks_an_error_outcome_without_leaking_details(
    chat_dependencies, client, quotas,
):
    chat_dependencies.vector_store.search_chunks.side_effect = RuntimeError("private upstream")

    response = client.post("/api/chat", json={"query": "q", "doc_id": "test-doc-id"})

    assert [event[0] for event in parse_sse_events(response)] == ["error", "done"]
    assert "private upstream" not in response.text
    final = quotas.mark_chat_status.await_args_list[-1]
    assert final.args[1] == "failed"
    assert final.args[2] == "stream_error"


async def test_cancelled_chat_is_marked_interrupted(quotas, monkeypatch):
    """A browser disconnect must release the status, not leave it streaming."""
    class Pipeline:
        async def retrieve_chunks(self, query, doc_id, *, user_id):
            return [RetrievedChunk("c1", doc_id, "text", 1, "s.pdf", 0.9)]

        def select_context_chunks(self, chunks):
            return chunks

        async def stream_answer(self, **kwargs):
            yield "partial"
            yield "never delivered"

        async def shutdown(self):
            pass

    async def pipeline(**kwargs):
        return Pipeline()

    monkeypatch.setattr("app.routers.chat.create_initialized_rag_pipeline", pipeline)
    from app.routers.chat import _stream_chat_sse

    stream = _stream_chat_sse(
        "q", "doc", OWNER, chat_request_id="00000000-0000-0000-0000-0000000000c1",
        quotas=quotas,
    )
    assert "event: sources" in await anext(stream)
    assert "event: token" in await anext(stream)
    await stream.aclose()

    statuses = [call.args[1] for call in quotas.mark_chat_status.await_args_list]
    assert statuses == ["streaming", "interrupted"]
