"""
POST /api/chat: authenticated SSE with sources, token, error, and done events.
"""
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.ai.document_summary import is_document_overview
from app.ai.rag_pipeline import create_initialized_rag_pipeline
from app.core.auth import require_supabase_user
from app.schemas import ChatRequest
from app.services.document_repository import DocumentRepository, get_document_repository
from app.services.rate_limiter import RateLimiter, get_rate_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


def _sse_message(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


async def _stream_chat_sse(query: str, doc_id: str, user_id: str, language: str = "vi",
                           document_id: str | None = None) -> AsyncIterator[str]:
    pipeline = None

    try:
        pipeline = await create_initialized_rag_pipeline()

        retrieved_chunks = await pipeline.retrieve_chunks(query, doc_id, user_id=user_id)
        if not is_document_overview(query):
            retrieved_chunks = pipeline.select_context_chunks(retrieved_chunks)
        sources_payload = [
            {"citation_id": number, "chunk_id": chunk.chunk_id, "doc_id": document_id or doc_id,
             "page": chunk.page, "source": chunk.source,
             "score": round(chunk.score, 4) if chunk.score is not None else None}
            for number, chunk in enumerate(retrieved_chunks, 1)
        ]
        yield _sse_message("sources", json.dumps(sources_payload))

        if not retrieved_chunks:
            fallback = (
                "Không tìm thấy đoạn văn nào trong tài liệu đủ liên quan với câu hỏi "
                "đang hỏi. Hãy thử hỏi cụ thể hơn hoặc yêu cầu tóm tắt tài liệu."
                if language == "vi"
                else "No sufficiently relevant passages were retrieved from this document. "
                "Try a more specific question or request a document summary."
            )
            if is_document_overview(query):
                fallback = (
                    "Không tìm thấy nội dung của tài liệu đang chọn. Hãy chọn lại hoặc tải lên lại PDF."
                    if language == "vi"
                    else "No content was found for the selected document. Select or upload the PDF again."
                )
            yield _sse_message("token", json.dumps(fallback))
            yield _sse_message("done", json.dumps("[DONE]"))
            return

        async for text_delta in pipeline.stream_answer(
            query=query,
            doc_id=doc_id,
            language=language,
            user_id=user_id,
            retrieved_chunks_override=retrieved_chunks,
        ):
            if text_delta:
                yield _sse_message("token", json.dumps(text_delta))

        yield _sse_message("done", json.dumps("[DONE]"))

    except Exception as e:
        logger.exception("Chat stream error: %s", e)
        yield _sse_message("error", json.dumps({"message": "Chat service unavailable. Please try again."}))
        yield _sse_message("done", json.dumps("[DONE]"))

    finally:
        if pipeline:
            await pipeline.shutdown()


@router.post("/chat")
async def chat(
    request: ChatRequest,
    user: dict = Depends(require_supabase_user),
    repository: DocumentRepository = Depends(get_document_repository),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> StreamingResponse:
    try:
        query = request.query.strip()
        doc_id = request.doc_id.strip()
        language = getattr(request, "language", "vi")
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        if not doc_id:
            raise HTTPException(status_code=400, detail="Document ID is required")
        user_id = str(user.get("id") or "")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid user: missing id.")
        document = await repository.get(user_id, doc_id)
        if document["status"] != "ready" or not document.get("active_index_id"):
            raise HTTPException(409, "Tài liệu chưa sẵn sàng để hỏi đáp.")

        await limiter.check(user_id, action="chat")
        return StreamingResponse(
            _stream_chat_sse(query, document["active_index_id"], user_id, language, document_id=doc_id),
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
