"""RQ document tasks. Redis owns metadata; Storage owns PDFs; Milvus owns chunks."""
import asyncio
import logging

from starlette.concurrency import run_in_threadpool
from rq import get_current_job

from app.core.config import get_config
from app.core.observability import bind_log_context
from app.services.document_repository import DocumentRepository
from app.services.job_queue import MAX_RETRIES
from app.services.provider_calls import UsageAttribution, UsageCollector
from app.services.pdf_indexing import InvalidPDFError, index_pdf_bytes
from app.services.supabase_pdf_storage import download_pdf, delete_pdf
from app.services.transcripts import TranscriptService
from app.storage.factory import create_connected_vector_store

logger = logging.getLogger(__name__)


async def remove_generations(user_id: str, generations: list[str]) -> None:
    if not generations:
        return
    store = await create_connected_vector_store()
    try:
        for generation in generations:
            await store.delete_document(generation, user_id=user_id)
    finally:
        await store.disconnect()


async def process_document(repository: DocumentRepository, doc_id: str, job_id: str,
                           attempt_number: int, retries_left: int) -> None:
    attempt = await repository.begin(doc_id, job_id, attempt_number)
    if not attempt:
        return  # Old job, duplicate execution, or an already committed result.
    document = attempt["document"]
    with bind_log_context(
        request_id=document.get("request_id"), workspace_id=document.get("workspace_id"),
        user_id=document["user_id"], doc_id=doc_id, job_id=job_id,
        attempt=attempt_number, kind=attempt["kind"],
    ):
        logger.info("document_job_started")
        try:
            await _process_attempt(repository, attempt, retries_left)
        except BaseException:
            logger.exception("document_job_failed")
            raise


async def _process_attempt(repository: DocumentRepository, attempt: dict, retries_left: int) -> None:
    document = attempt["document"]
    uid, doc_id = document["user_id"], document["doc_id"]
    job_id = attempt["job_id"]
    usage = (
        UsageCollector(UsageAttribution(
            workspace_id=document.get("workspace_id"), user_id=uid, doc_id=doc_id, job_id=job_id,
        ))
        if attempt["kind"] == "index" else None
    )
    try:
        try:
            if attempt["kind"] == "delete":
                await TranscriptService(repository.config).hide_for_document(
                    document.get("workspace_id") or uid, uid, doc_id,
                    deleted_at=document.get("delete_requested_at"),
                )
                await remove_generations(uid, document["generations"])
                await run_in_threadpool(delete_pdf, document["storage_key"])
                if await repository.finish(attempt):
                    logger.info("document_job_completed")
            else:
                # Retried jobs clean earlier partial indexes before writing a fresh one.
                await remove_generations(uid, [item for item in document["generations"] if item != attempt["attempt_id"]])
                content = await run_in_threadpool(download_pdf, document["storage_key"])
                kwargs = {"usage": usage} if usage and usage.enabled else {}
                result = await index_pdf_bytes(
                    content, document["name"], attempt["attempt_id"], user_id=uid, **kwargs,
                )
                if await repository.finish(attempt, chunks_count=result.chunks_count, warnings=result.warnings):
                    logger.info("document_job_completed", extra={"chunks_count": result.chunks_count})
        except Exception as exc:
            # Read before recording failure: a lost publish response may have committed.
            current = await repository.internal_document(doc_id)
            if current and (current.get("active_index_id") == attempt["attempt_id"]
                            or (attempt["kind"] == "delete" and current["status"] == "deleted")):
                return
            permanent = isinstance(exc, InvalidPDFError)
            await repository.finish(attempt, retryable=not permanent and retries_left > 0, error=(
                "Không thể xóa hết dữ liệu. Vui lòng thử lại." if attempt["kind"] == "delete" else
                "Không thể xử lý PDF. Kiểm tra tệp có văn bản, rồi thử lại hoặc tải lại tài liệu."
            ))
            if not permanent:
                raise  # RQ owns timeout, retry scheduling and abandoned-job maintenance.
            logger.info("document_pdf_rejected", extra={"error_code": "invalid_pdf"})
        # Failed generations remain registered for the next retry/delete. No finally
        # deletion: a publication response can be lost after Redis has committed it.
    finally:
        if usage is not None:
            await usage.flush()


def run_document(doc_id: str) -> None:
    job = get_current_job()
    if job is None:
        raise RuntimeError("Document tasks must run inside an RQ worker")
    retries_left = job.retries_left or 0
    # RQ's retry counter also fences duplicate entries for the same execution.
    attempt_number = MAX_RETRIES + 1 - retries_left
    asyncio.run(process_document(DocumentRepository(get_config()), doc_id, job.id, attempt_number, retries_left))


def index_document(doc_id: str) -> None:
    run_document(doc_id)


def delete_document(doc_id: str) -> None:
    run_document(doc_id)
