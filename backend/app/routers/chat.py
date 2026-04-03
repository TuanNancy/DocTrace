"""
POST /api/chat: SSE stream with event types token, sources, [DONE].
Updated to use new RAG agent architecture with streaming support.
"""
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.ai.rag_agent import create_rag_agent_with_defaults
from app.core.auth import require_supabase_user
from app.models.document import QueryMode
from app.schemas import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


def _sse_message(event: str, data: str) -> str:
    """Format one SSE message: event type + data line."""
    return f"event: {event}\ndata: {data}\n\n"


async def _stream_chat_sse(query: str, doc_id: str, language: str = "vi") -> AsyncIterator[str]:
    """
    Yield SSE events: sources (retrieval), then LLM tokens (OpenRouter), then done.

    Retrieval uses embeddings + Milvus; answers use the same OpenRouter key as configured for chat.
    """
    agent = None

    try:
        agent = await create_rag_agent_with_defaults()

        # 1) Retrieve chunks once (embedding + vector search)
        retrieved_chunks = await agent._retrieve_chunks(query, doc_id)
        sources_payload = [
            {"page": chunk.page, "source": chunk.source, "score": round(chunk.score, 4)}
            for chunk in retrieved_chunks
        ]
        yield _sse_message("sources", json.dumps(sources_payload))

        if not retrieved_chunks:
            # Avoid calling the LLM with empty context (models often refuse "summarize PDF" with no text)
            fallback = (
                "Không tìm thấy đoạn văn nào trong tài liệu đủ liên quan với câu hỏi "
                "(có thể do ngưỡng MIN_RELEVANCE_SCORE quá cao hoặc câu hỏi quá khác nội dung đã index). "
                "Hãy thử hạ MIN_RELEVANCE_SCORE trong .env (ví dụ 0.25) hoặc đặt câu hỏi gần với nội dung file hơn."
                if language == "vi"
                else "No sufficiently relevant passages were retrieved from this document. "
                "Try lowering MIN_RELEVANCE_SCORE in .env or rephrasing your question."
            )
            yield _sse_message("token", json.dumps(fallback))
            yield _sse_message("done", json.dumps("[DONE]"))
            return

        # 2) Stream LLM answer (OpenRouter chat completions) with the same context
        async for token in agent.process_query_stream(
            query=query,
            doc_id=doc_id,
            mode=QueryMode.RAG,
            language=language,
            retrieved_chunks_override=retrieved_chunks,
        ):
            safe = json.dumps(token) if token else ""
            yield _sse_message("token", safe)

        yield _sse_message("done", json.dumps("[DONE]"))

    except Exception as e:
        logger.exception("Chat stream error: %s", e)
        yield _sse_message("error", json.dumps({"message": str(e)}))
        yield _sse_message("done", json.dumps("[DONE]"))

    finally:
        if agent:
            await agent.shutdown()


@router.post("/chat")
async def chat(
    request: ChatRequest,
    _user: dict = Depends(require_supabase_user),
) -> StreamingResponse:
    """
    RAG chat: retrieve chunks by doc_id, then stream LLM response via SSE.
    Updated to use new RAG agent architecture.

    Events:
        - token (data = JSON string of token)
        - sources (data = JSON array of {page, source, score})
        - done (data = [DONE])

    Request body:
        {
            "query": "user question",
            "doc_id": "document id",
            "language": "vi" (optional, defaults to "vi")
        }
    """
    try:
        query = request.query.strip()
        doc_id = request.doc_id.strip()
        language = getattr(request, "language", "vi")
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        if not doc_id:
            raise HTTPException(status_code=400, detail="Document ID is required")

        return StreamingResponse(
            _stream_chat_sse(query, doc_id, language),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Chat error: %s", e)
        raise HTTPException(status_code=500, detail="Chat stream failed.") from e
