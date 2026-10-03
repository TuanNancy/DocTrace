"""Deliver the transactional outbox and reconcile lost/abandoned RQ jobs.

Run independently of the worker: a long PDF must not block delivery or recovery.
Redis connection errors propagate; they are never interpreted as a missing job.
"""
import asyncio
from datetime import datetime, timezone
import logging
import signal
import time

from starlette.concurrency import run_in_threadpool

from app.core.config import get_config
from app.services.document_repository import DocumentRepository
from app.services.job_queue import DocumentQueue

logger = logging.getLogger(__name__)
LIVE_STATES = {"queued", "started", "scheduled", "deferred"}


def future(value: str | None) -> bool:
    return bool(value and datetime.fromisoformat(value) > datetime.now(timezone.utc))


async def dispatch_operation(repository: DocumentRepository, queue: DocumentQueue, operation: dict) -> None:
    if future(operation["available_at"]):
        return
    status = await run_in_threadpool(queue.status, operation)
    expired_attempt = operation["attempt_expires_at"] is not None and not future(operation["attempt_expires_at"])
    if status in LIVE_STATES and not expired_attempt:
        # RQ owns healthy executions and scheduled retries. An expired publication
        # deadline also permits recovery of a stuck started key whose registry was lost.
        return
    if future(operation["attempt_expires_at"]):
        return  # A missing Redis key does not prove its old process stopped.
    if status is None and operation["attempt_id"] is None:
        if operation["kind"] == "delete" and await repository.deletion_blocked(operation["doc_id"]):
            return
        await run_in_threadpool(queue.enqueue, operation)
        await repository.dispatched(operation)
        logger.info("Delivered operation=%s doc=%s delivery=%s", operation["operation_id"],
                    operation["doc_id"], operation["delivery"])
        return
    # An unfinished attempt with an expired deadline was interrupted. RQ may have marked
    # it failed with AbandonedJobError; recover within the durable three-attempt budget.
    interrupted = operation["attempt_expires_at"] is not None
    terminal = status in {"failed", "stopped", "canceled"} and not interrupted
    await repository.recover(operation, terminal=terminal)


async def dispatch_once(repository: DocumentRepository, queue: DocumentQueue) -> None:
    async for operation in repository.pending_operations():
        await dispatch_operation(repository, queue, operation)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = get_config()
    repository, queue = DocumentRepository(config), DocumentQueue(config)
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    next_maintenance = 0.0
    try:
        while not stop.is_set():
            try:
                await dispatch_once(repository, queue)
                if time.monotonic() >= next_maintenance:
                    await repository.recover_uploads()
                    for document in await repository.cleanup_due():
                        await run_in_threadpool(queue.enqueue_cleanup, document)
                    logger.info("Dispatcher heartbeat: outbox checked")
                    next_maintenance = time.monotonic() + 30
            except Exception:
                logger.exception("Dispatcher will retry delivery/reconciliation")
            try:
                await asyncio.wait_for(stop.wait(), timeout=config.document_dispatch_poll_seconds)
            except asyncio.TimeoutError:
                pass
    finally:
        queue.close()


if __name__ == "__main__":
    asyncio.run(main())
