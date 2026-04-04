"""
Tests for POST /api/chat: validation and SSE stream (mocked).
"""
from unittest.mock import patch

from fastapi.testclient import TestClient


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


@patch("app.routers.chat._stream_chat_sse")
def test_chat_sse_stream(mock_stream, client: TestClient) -> None:
    """200 + SSE when mocked stream yields events."""

    async def fake_stream(*_a, **_k):
        yield 'event: token\ndata: "Hi"\n\n'
        yield 'event: sources\ndata: [{"page":1,"source":"doc.pdf","score":0.9}]\n\n'
        yield "event: done\ndata: [DONE]\n\n"

    mock_stream.return_value = fake_stream()

    response = client.post(
        "/api/chat",
        json={"query": "Chào", "doc_id": "test-doc-id"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    text = response.text
    assert "event: token" in text
    assert "event: sources" in text
    assert "event: done" in text


@patch("app.routers.chat._stream_chat_sse")
def test_chat_sse_error_path(mock_stream, client: TestClient) -> None:
    """SSE can include error + done."""

    async def fake_stream(*_a, **_k):
        yield 'event: error\ndata: {"message": "fail"}\n\n'
        yield "event: done\ndata: [DONE]\n\n"

    mock_stream.return_value = fake_stream()

    response = client.post(
        "/api/chat",
        json={"query": "Anything", "doc_id": "nonexistent-doc"},
    )
    assert response.status_code == 200
    assert "event: error" in response.text
