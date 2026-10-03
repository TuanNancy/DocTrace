from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.dispatcher import dispatch_operation


def timestamp(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


@pytest.fixture
def operation():
    return {"operation_id": "operation", "doc_id": "doc", "kind": "index", "delivery": 0,
            "attempt_id": None, "attempt_expires_at": None, "available_at": timestamp(-30)}


async def test_pending_intent_is_enqueued_before_marking_dispatched(operation):
    repository, queue = AsyncMock(), MagicMock()
    queue.status.return_value = None
    await dispatch_operation(repository, queue, operation)
    queue.enqueue.assert_called_once_with(operation)
    repository.dispatched.assert_awaited_once_with(operation)


async def test_lost_redis_connection_is_not_treated_as_missing_job(operation):
    repository, queue = AsyncMock(), MagicMock()
    queue.status.side_effect = RedisConnectionError()
    with pytest.raises(RedisConnectionError):
        await dispatch_operation(repository, queue, operation)
    repository.recover.assert_not_awaited()
    queue.enqueue.assert_not_called()


async def test_failed_delivery_is_not_marked_dispatched(operation):
    repository, queue = AsyncMock(), MagicMock()
    queue.status.return_value = None
    queue.enqueue.side_effect = RedisConnectionError()
    with pytest.raises(RedisConnectionError):
        await dispatch_operation(repository, queue, operation)
    repository.dispatched.assert_not_awaited()


@pytest.mark.parametrize("status", ["queued", "started", "scheduled", "deferred"])
async def test_rq_owns_active_jobs_and_scheduled_retries(operation, status):
    repository, queue = AsyncMock(), MagicMock()
    queue.status.return_value = status
    await dispatch_operation(repository, queue, operation)
    repository.recover.assert_not_awaited()
    queue.enqueue.assert_not_called()


async def test_missing_job_waits_for_possible_old_writer(operation):
    repository, queue = AsyncMock(), MagicMock()
    queue.status.return_value = None
    operation.update(attempt_id="attempt", attempt_expires_at=timestamp(60))
    await dispatch_operation(repository, queue, operation)
    repository.recover.assert_not_awaited()
    queue.enqueue.assert_not_called()


@pytest.mark.parametrize("status", [None, "failed", "finished", "started", "queued", "scheduled"])
async def test_interrupted_attempt_is_recovered_under_database_budget(operation, status):
    repository, queue = AsyncMock(), MagicMock()
    queue.status.return_value = status
    operation.update(attempt_id="attempt", attempt_expires_at=timestamp(-1))
    await dispatch_operation(repository, queue, operation)
    repository.recover.assert_awaited_once_with(operation, terminal=False)


async def test_terminal_rq_failure_repairs_metadata_if_task_never_started(operation):
    repository, queue = AsyncMock(), MagicMock()
    queue.status.return_value = "failed"
    await dispatch_operation(repository, queue, operation)
    repository.recover.assert_awaited_once_with(operation, terminal=True)


async def test_redis_loss_does_not_skip_backoff(operation):
    repository, queue = AsyncMock(), MagicMock()
    operation["available_at"] = timestamp(60)
    await dispatch_operation(repository, queue, operation)
    queue.status.assert_not_called()


async def test_delete_waits_for_superseded_index_writer(operation):
    repository, queue = AsyncMock(), MagicMock()
    operation["kind"] = "delete"
    queue.status.return_value = None
    repository.deletion_blocked.return_value = True
    await dispatch_operation(repository, queue, operation)
    queue.enqueue.assert_not_called()
