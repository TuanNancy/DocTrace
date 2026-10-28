"""
POST /api/chat: authenticated SSE with sources, token, error, and done events.
"""
import asyncio
import json
import logging
from time import perf_counter
from typing import AsyncIterator
from uuid import uuid4

from anyio import CancelScope
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.ai.budget import BudgetExceededError, RequestBudget, budget_for
from app.ai.document_summary import is_document_overview
from app.ai.prompts import PROMPT_VERSION
from app.ai.rag_pipeline import create_initialized_rag_pipeline
from app.ai.routing import RouteDecision, choose_route
from app.core.config import get_config
from app.core.workspace import require_workspace
from app.schemas import ChatRequest
from app.services.answer_cache import AnswerCache, cache_key, get_answer_cache
from app.services.document_repository import DocumentRepository, get_document_repository
from app.services.provider_calls import UsageAttribution, UsageCollector
from app.services.quotas import (
    QuotaService, duplicate_error, get_quota_service,
)
from app.services.rate_limiter import RateLimiter, get_rate_limiter
from app.services.transcripts import TranscriptService, get_transcript_service
from app.services.workspaces import WorkspaceContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


def _sse_message(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


async def _stream_chat_sse(query: str, doc_id: str, user_id: str, language: str = "vi",
                           document_id: str | None = None,
                           workspace_id: str | None = None,
                           index_id: str | None = None,
                           plan: str = "free",
                           route: RouteDecision | None = None,
                           budget: RequestBudget | None = None,
                           cache: AnswerCache | None = None,
                           usage: UsageCollector | None = None,
                           chat_request_id: str | None = None,
                           assistant_message_id: str | None = None,
                           quotas: QuotaService | None = None,
                           transcripts: TranscriptService | None = None) -> AsyncIterator[str]:
    pipeline = None
    started = perf_counter()
    first_token_ms: int | None = None
    # Completion is only published after the done event is yielded. A closed
    # generator or a cancelled task therefore stays "interrupted" unless the
    # provider actually finished its answer.
    outcome = "interrupted"
    error_code: str | None = None
    cache_hit = False
    answer_parts: list[str] = []
    sources_payload: list[dict] = []
    stream_config = get_config()
    selected_route = route or RouteDecision(str(getattr(stream_config, "model", "")), "routing_off", 0, 0)
    cache_policy = cache_key(
        workspace_id=workspace_id or "", user_id=user_id, doc_id=document_id or doc_id,
        index_id=index_id or doc_id, query=query, language=language,
        model=selected_route.model, prompt_version=PROMPT_VERSION,
        retrieval_top_k=getattr(stream_config, "retrieval_top_k", 8),
        min_relevance_score=getattr(stream_config, "min_relevance_score", 0.32),
        context_max_chars=getattr(stream_config, "context_max_chars", 12000),
        max_tokens=getattr(stream_config, "max_tokens", 2048),
        temperature=getattr(stream_config, "temperature", 0.7),
        summary_max_calls=getattr(stream_config, "summary_max_calls", 8),
        overview=is_document_overview(query),
    ) if cache is not None and cache.enabled else None

    if quotas is not None and chat_request_id:
        try:
            await quotas.mark_chat_status(chat_request_id, "streaming")
        except Exception:
            # Admission already consumed quota; status telemetry must never
            # prevent the answer from streaming.
            logger.warning("chat_status_write_failed", exc_info=True)
    if transcripts is not None and assistant_message_id:
        try:
            await transcripts.mark_streaming(assistant_message_id)
        except Exception:
            logger.warning("chat_transcript_write_failed", exc_info=True)

    try:
        if cache is not None and cache_policy:
            try:
                cached = await cache.get(cache_policy, doc_id=document_id or doc_id)
            except Exception:
                cached = None
                logger.warning("answer_cache_failed", exc_info=True)
            if cached:
                cache_hit = True
                sources_payload = cached["sources"]
                answer = cached["answer"]
                answer_parts.append(answer)
                first_token_ms = round((perf_counter() - started) * 1000)
                logger.info("answer_cache_hit")
                yield _sse_message("sources", json.dumps(sources_payload))
                yield _sse_message("token", json.dumps(answer))
                yield _sse_message("done", json.dumps("[DONE]"))
                outcome = "completed"
                return

        pipeline = await create_initialized_rag_pipeline(
            usage=usage, budget=budget, model=selected_route.model,
        )

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
            answer_parts.append(fallback)
            first_token_ms = round((perf_counter() - started) * 1000)
            yield _sse_message("token", json.dumps(fallback))
            yield _sse_message("done", json.dumps("[DONE]"))
            outcome = "completed"
            return

        async for text_delta in pipeline.stream_answer(
            query=query,
            doc_id=doc_id,
            language=language,
            user_id=user_id,
            retrieved_chunks_override=retrieved_chunks,
        ):
            if text_delta:
                if first_token_ms is None:
                    first_token_ms = round((perf_counter() - started) * 1000)
                answer_parts.append(text_delta)
                yield _sse_message("token", json.dumps(text_delta))

        yield _sse_message("done", json.dumps("[DONE]"))
        outcome = "completed"

    except (asyncio.CancelledError, GeneratorExit):
        outcome = "interrupted"
        raise
    except BudgetExceededError:
        outcome = "failed"
        error_code = "budget_exceeded"
        logger.warning("request_budget_exceeded")
        message = (
            "Câu hỏi vượt giới hạn chi phí của một yêu cầu. Hãy hỏi ngắn hơn hoặc chọn tài liệu khác."
            if language == "vi" else
            "This question exceeds the per-request cost limit. Ask a shorter question or select another document."
        )
        yield _sse_message("error", json.dumps({"message": message}))
        yield _sse_message("done", json.dumps("[DONE]"))
    except Exception:
        outcome = "failed"
        error_code = "stream_error"
        logger.exception("chat_stream_failed")
        yield _sse_message("error", json.dumps({"message": "Chat service unavailable. Please try again."}))
        yield _sse_message("done", json.dumps("[DONE]"))

    finally:
        latency_ms = round((perf_counter() - started) * 1000)
        try:
            if pipeline:
                await pipeline.shutdown()
        finally:
            with CancelScope(shield=True):
                # Admission already consumed the question, so the terminal
                # status, transcript and cost rows must survive a browser
                # disconnect.
                if transcripts is not None and assistant_message_id:
                    try:
                        await transcripts.finalize_message(
                            assistant_message_id,
                            {"completed": "complete", "failed": "error"}.get(outcome, "interrupted"),
                            "".join(answer_parts),
                            sources_payload,
                        )
                    except Exception:
                        logger.warning("chat_transcript_write_failed", exc_info=True)
                if quotas is not None and chat_request_id:
                    try:
                        await quotas.mark_chat_status(chat_request_id, outcome, error_code)
                        await quotas.record_timing(
                            chat_request_id, latency_ms, first_token_ms, cache_hit=cache_hit,
                        )
                    except Exception:
                        logger.warning("chat_status_write_failed", exc_info=True)
                if (cache is not None and cache_policy and outcome == "completed" and not cache_hit
                        and sources_payload and answer_parts):
                    try:
                        await cache.put(cache_policy, {
                            "answer": "".join(answer_parts), "sources": sources_payload,
                        })
                    except Exception:
                        logger.warning("answer_cache_failed", exc_info=True)
                if usage is not None:
                    await usage.flush()


@router.post("/chat")
async def chat(
    request: ChatRequest,
    workspace: WorkspaceContext = Depends(require_workspace),
    repository: DocumentRepository = Depends(get_document_repository),
    limiter: RateLimiter = Depends(get_rate_limiter),
    quotas: QuotaService = Depends(get_quota_service),
    transcripts: TranscriptService = Depends(get_transcript_service),
    cache: AnswerCache = Depends(get_answer_cache),
) -> StreamingResponse:
    try:
        query = request.query.strip()
        doc_id = request.doc_id.strip()
        language = getattr(request, "language", "vi")
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        if not doc_id:
            raise HTTPException(status_code=400, detail="Document ID is required")
        user_id = workspace.user_id
        document = await repository.get(workspace.workspace_id, user_id, doc_id)
        if document["status"] != "ready" or not document.get("active_index_id"):
            raise HTTPException(409, "Tài liệu chưa sẵn sàng để hỏi đáp.")
        config = get_config()
        overview = is_document_overview(query)
        route = choose_route(config, plan=workspace.plan, query=query, overview=overview)
        logger.info("rag_route_selected", extra={"route": route.reason, "model": route.model})
        budget = budget_for(config, route)

        # A retried submit must not spend a second rate-limit token or quota
        # question. admit_chat repeats this check atomically to also close the
        # race where two identical requests arrive together.
        request_id = str(request.request_id or uuid4())
        existing = await quotas.existing_chat(workspace.workspace_id, user_id, request_id)
        if existing:
            raise duplicate_error(existing)

        await limiter.check(user_id, action="chat")
        admission = await quotas.admit_chat(
            workspace.workspace_id, user_id, request_id, doc_id, workspace.plan,
            query=query, index_id=document["active_index_id"],
        )
        usage = UsageCollector(UsageAttribution(
            workspace_id=workspace.workspace_id, user_id=user_id, doc_id=doc_id,
            request_id=request_id,
        ), config=get_config())
        return StreamingResponse(
            _stream_chat_sse(
                query, document["active_index_id"], user_id, language,
                document_id=doc_id, workspace_id=workspace.workspace_id,
                index_id=document["active_index_id"], plan=workspace.plan,
                route=route, budget=budget, cache=cache, usage=usage,
                chat_request_id=admission["chat_request_id"],
                assistant_message_id=admission.get("assistant_message_id"),
                quotas=quotas, transcripts=transcripts,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Conversation-Id": admission.get("conversation_id", ""),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("chat_failed")
        raise HTTPException(status_code=500, detail="Chat stream failed.") from e
