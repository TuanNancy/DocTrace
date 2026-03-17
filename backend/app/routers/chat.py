"""
POST /api/chat: SSE stream with event types token, sources, [DONE].
Updated to use new RAG agent architecture with streaming support.
"""
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.ai.rag_agent import create_rag_agent_with_defaults
from app.core.config import get_config
from app.models.document import QueryMode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


def _sse_message(event: str, data: str) -> str:
    """Format one SSE message: event type + data line."""
    return f"event: {event}\ndata: {data}\n\n"


async def _stream_chat_sse(query: str, doc_id: str, language: str = "vi") -> AsyncIterator[str]:
    """
    Yield SSE events: token, sources, done using new RAG agent architecture.

    Args:
        query: User query
        doc_id: Document ID to search within
        language: Language for prompts ("vi" or "en")

    Yields:
        SSE formatted messages
    """
    config = get_config()
    agent = None

    try:
        # Create RAG agent
        agent = await create_rag_agent_with_defaults()

        # Process query with streaming
        retrieved_chunks = []
        answer_tokens = []

        async for token in agent.process_query_stream(
            query=query,
            doc_id=doc_id,
            mode=QueryMode.RAG,
            language=language,
        ):
            # Collect tokens for the answer
            answer_tokens.append(token)

            # Stream each token as SSE event
            safe = json.dumps(token) if token else ""
            yield _sse_message("token", safe)

        # Get retrieved chunks from the agent's last query
        # We need to retrieve chunks separately since streaming doesn't return them
        query_vector = agent.embedder.embed_documents([query])
        if query_vector:
            retrieved_chunks = await agent.storage.search_chunks(
                query_vector=query_vector[0],
                doc_id=doc_id,
                top_k=config.retrieval_top_k,
                min_score=config.min_relevance_score,
            )

        # If no chunks found, emit error
        if not retrieved_chunks:
            yield _sse_message("error", json.dumps({"message": "Không tìm thấy nội dung liên quan cho tài liệu này."}))
            yield _sse_message("done", "[DONE]")
            return

        # Emit sources
        sources_payload = [
            {"page": chunk.page, "source": chunk.source, "score": round(chunk.score, 4)}
            for chunk in retrieved_chunks
        ]
        yield _sse_message("sources", json.dumps(sources_payload))

        # Done
        yield _sse_message("done", "[DONE]")

    except Exception as e:
        logger.exception("Chat stream error: %s", e)
        yield _sse_message("error", json.dumps({"message": str(e)}))
        yield _sse_message("done", "[DONE]")

    finally:
        # Cleanup agent
        if agent:
            await agent.shutdown()


@router.post("/chat")
async def chat(request: dict) -> StreamingResponse:
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
        query = request.get("query", "")
        doc_id = request.get("doc_id", "")
        language = request.get("language", "vi")

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
