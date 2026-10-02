"""Run with `python -m app.worker`. PostgreSQL leases survive API/worker restarts.

Each claim indexes into its own generation. Only a valid lease can publish that
generation, so expired workers cannot corrupt a newer retry or resurrect a deletion.
"""
import asyncio
import logging
import signal
import time
from fastapi import HTTPException

from starlette.concurrency import run_in_threadpool

from app.core.config import get_config
from app.services.document_repository import DocumentRepository
from app.services.pdf_indexing import index_pdf_bytes
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


async def process_job(repository: DocumentRepository, job: dict) -> None:
    document = job["document"]
    uid, doc_id = document["user_id"], document["doc_id"]
    generation = job["lease_token"]
    published = False
    try:
        if job["kind"] == "delete":
            await remove_generations(uid, await repository.generations(doc_id))
            await run_in_threadpool(delete_pdf, document["storage_key"])
            await repository.finish(job)
        else:
            content = await run_in_threadpool(download_pdf, document["storage_key"])
            result = await index_pdf_bytes(content, document["name"], generation, user_id=uid)
            published = await repository.finish(job, chunks_count=result.chunks_count, warnings=result.warnings)
            if published:
                old = [item for item in await repository.generations(doc_id) if item != generation]
                await remove_generations(uid, old)
    except asyncio.CancelledError:
        # Leave the durable job running; its lease expires and another worker retries.
        raise
    except Exception:
        logger.exception("Document job failed: %s", job["job_id"])
        if not published:
            await repository.finish(job, error=(
                "Không thể xóa hết dữ liệu. Vui lòng thử lại."
                if job["kind"] == "delete" else
                "Không thể xử lý PDF. Kiểm tra tệp có văn bản, rồi thử lại hoặc tải lại tài liệu."
            ))
    finally:
        if job["kind"] == "index" and not published:
            try:
                # A finish RPC may commit even if its HTTP response is lost. Never
                # remove a potentially published index without rereading metadata.
                try:
                    current = await repository.get(uid, doc_id)
                except HTTPException as exc:
                    if exc.status_code != 404:
                        raise
                    current = {}
                if current.get("active_index_id") != generation:
                    await remove_generations(uid, [generation])
            except Exception:
                # The generation stays registered so a retry/delete can clean it up.
                logger.exception("Could not clean unpublished generation %s", generation)


async def run_claim(repository: DocumentRepository, job: dict) -> None:
    task = asyncio.create_task(process_job(repository, job))
    try:
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=max(5, repository.config.document_job_lease_seconds / 3))
            if done:
                break
            if not await repository.heartbeat(job):
                logger.warning("Document job lease lost: %s", job["job_id"])
                task.cancel()
                break
        await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def sweep_tombstones(repository: DocumentRepository) -> None:
    """Re-delete tombstones to catch remote writes finishing after a lease expired.

    A cancelled Python task cannot stop an already-running S3/Milvus thread. The
    published pointer is already revoked; this sweep guarantees eventual physical cleanup.
    """
    for document in await repository.tombstones_due():
        try:
            await remove_generations(document["user_id"], await repository.generations(document["doc_id"]))
            await run_in_threadpool(delete_pdf, document["storage_key"])
            await repository.tombstone_cleaned(document["doc_id"])
        except Exception:
            logger.exception("Tombstone cleanup will be retried: %s", document["doc_id"])


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = get_config()
    repository = DocumentRepository(config)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    logger.info("Document worker started")
    next_sweep = 0.0
    while not stop.is_set():
        try:
            if time.monotonic() >= next_sweep:
                next_sweep = time.monotonic() + 60
                await sweep_tombstones(repository)
            job = await repository.claim()
            if job:
                await run_claim(repository, job)
                continue
        except asyncio.CancelledError:
            if stop.is_set():
                break
        except Exception:
            logger.exception("Worker could not claim/finish a job")
        try:
            await asyncio.wait_for(stop.wait(), timeout=config.document_worker_poll_seconds)
        except asyncio.TimeoutError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
