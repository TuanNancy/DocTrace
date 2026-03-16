"""
POST /api/chat: SSE stream with event types token, sources, [DONE].
X-Accel-Buffering: no to disable Nginx buffering.
"""
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.documents.retrieval import (
    SYSTEM_PROMPT_VI,
    build_context,
    search_chunks,
)
from app.providers.openrouter import stream_answer
from app.schemas import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


def _sse_message(event: str, data: str) -> str:
    """Format one SSE message: event type + data line."""
    return f"event: {event}\ndata: {data}\n\n"


async def _stream_chat_sse(query: str, doc_id: str) -> AsyncIterator[str]:
    """Yield SSE events: token, sources, done."""
    chunks = search_chunks(query, doc_id)
    if not chunks:
        yield _sse_message("error", json.dumps({"message": "Không tìm thấy nội dung liên quan cho tài liệu này."}))
        yield _sse_message("done", "[DONE]")
        return

    # 1. Emit sources first (page, source, score)
    sources_payload = [
        {"page": c.page, "source": c.source, "score": round(c.score, 4)}
        for c in chunks
    ]
    yield _sse_message("sources", json.dumps(sources_payload))

    # 2. Build context and messages
    context = build_context(chunks)
    system_content = f"{SYSTEM_PROMPT_VI}\n\nNgữ cảnh tài liệu:\n\n{context}"
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": query},
    ]

    # 3. Stream tokens
    try:
        async for token in stream_answer(messages):
            # SSE data: escape newlines for multi-line content
            safe = json.dumps(token) if token else ""
            yield _sse_message("token", safe)
    except Exception as e:
        logger.exception("LLM stream error: %s", e)
        yield _sse_message("error", json.dumps({"message": str(e)}))

    # 4. Done
    yield _sse_message("done", "[DONE]")


@router.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """
    RAG chat: retrieve chunks by doc_id, then stream LLM response via SSE.
    Events: token (data = JSON string of token), sources (data = JSON array of {page, source, score}), done (data = [DONE]).
    """
    try:
        return StreamingResponse(
            _stream_chat_sse(request.query, request.doc_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as e:
        logger.exception("Chat error: %s", e)
        raise HTTPException(status_code=500, detail="Chat stream failed.") from e
