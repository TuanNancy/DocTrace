"""Document work, independent of RQ's scheduling machinery.

An operation identifies user intent; each attempt gets a fresh Milvus generation.
Only an unexpired, current attempt can publish. Postgres also keeps the retry budget
and generation inventory when Redis loses keys. RQ exceptions must not be swallowed.
"""
import asyncio
import logging

from starlette.concurrency import run_in_threadpool

from app.core.config import get_config
from app.services.document_repository import DocumentRepository
from app.services.pdf_indexing import InvalidPDFError, index_pdf_bytes
from app.services.supabase_pdf_storage import download_pdf, delete_pdf
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


async def process_document(repository: DocumentRepository, operation_id: str, delivery: int, kind: str) -> None:
    timeout = (repository.config.document_index_timeout_seconds if kind == "index"
               else repository.config.document_delete_timeout_seconds)
    attempt = await repository.begin(operation_id, delivery, timeout)
    if not attempt:
        return  # Superseded, already completed, duplicate delivery, or deletion waiting for a writer.
    document = attempt["document"]
    uid, doc_id = document["user_id"], document["doc_id"]
    logger.info("Started operation=%s attempt=%s doc=%s kind=%s", operation_id, attempt["attempt_id"], doc_id, kind)
    try:
        if attempt["kind"] == "delete":
            await remove_generations(uid, await repository.generations(doc_id))
            await run_in_threadpool(delete_pdf, document["storage_key"])
            await repository.finish(attempt)
        else:
            content = await run_in_threadpool(download_pdf, document["storage_key"])
            result = await index_pdf_bytes(content, document["name"], attempt["attempt_id"], user_id=uid)
            await repository.finish(attempt, chunks_count=result.chunks_count, warnings=result.warnings)
    except Exception as exc:
        # Read before recording failure: a lost publish response may have committed.
        current = await repository.internal_document(doc_id)
        if current and (current.get("active_index_id") == attempt["attempt_id"]
                        or (attempt["kind"] == "delete" and current["status"] == "deleted")):
            return
        permanent = isinstance(exc, InvalidPDFError)
        await repository.finish(attempt, retryable=not permanent, error=(
            "Không thể xóa hết dữ liệu. Vui lòng thử lại." if attempt["kind"] == "delete" else
            "Không thể xử lý PDF. Kiểm tra tệp có văn bản, rồi thử lại hoặc tải lại tài liệu."
        ))
        if not permanent:
            raise  # RQ applies Retry; a killed process is repaired by the dispatcher instead.
        logger.info("PDF rejected operation=%s doc=%s", operation_id, doc_id)
    # Cleanup is a separate, durable task. It cannot convert a committed success into failure.
    # No finally deletion: its database response may be lost, or a remote write may finish late.


def index_document(operation_id: str, delivery: int) -> None:
    asyncio.run(process_document(DocumentRepository(get_config()), operation_id, delivery, "index"))


def delete_document(operation_id: str, delivery: int) -> None:
    asyncio.run(process_document(DocumentRepository(get_config()), operation_id, delivery, "delete"))


async def cleanup(repository: DocumentRepository, doc_id: str, expected: str) -> None:
    document = await repository.internal_document(doc_id)
    if not document:
        return
    # SQL excludes published and live-attempt generations; deadlines fence late publishers.
    await remove_generations(document["user_id"], await repository.cleanup_candidates(doc_id))
    if document["status"] == "deleted":
        await run_in_threadpool(delete_pdf, document["storage_key"])
    await repository.cleanup_finished(doc_id, expected)


def cleanup_document(doc_id: str, expected: str) -> None:
    asyncio.run(cleanup(DocumentRepository(get_config()), doc_id, expected))
