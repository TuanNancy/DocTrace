"""Privacy-safe terminal failures, durable beyond RQ's failure TTL.

Catalog failure and a Redis outbox entry commit together. A bounded idempotent
drain stores them in Postgres and only acknowledges after SQL commit. DB outages
retain the outbox; worker maintenance and admin reads retry the drain.
"""
import json
import logging
from itertools import islice
from uuid import NAMESPACE_URL, uuid5

from redis import Redis
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.core.config import AppConfig
from app.core.observability import valid_request_id
from app.db import session_scope

logger = logging.getLogger(__name__)
OUTBOX_KEY = "doctrace:failures:v1:pending"
ERROR_MESSAGES = {
    "invalid_pdf": "PDF cannot be indexed. Check that it contains readable text.",
    "index_failed": "Document indexing failed after retries.",
    "delete_failed": "Document cleanup failed after retries.",
    "job_interrupted": "Document job was interrupted or its queue record expired.",
}


def stage_failure(pipeline, document: dict, error_code: str) -> None:
    """Called inside the catalog MULTI; no error messages or content are copied."""
    if error_code not in ERROR_MESSAGES:
        raise ValueError("Unregistered failure code")
    attempt = document.get("attempt_number", 0)
    event_id = str(uuid5(NAMESPACE_URL, f"doctrace:failure:{document['doc_id']}:{document['job_id']}:{attempt}"))
    request_id = document.get("request_id")
    event = {
        "id": event_id, "workspace_id": document["workspace_id"],
        "owner_user_id": document["owner_user_id"], "doc_id": document["doc_id"],
        "job_id": document["job_id"], "attempt": attempt,
        "kind": document["job_kind"], "error_code": error_code,
        "request_id": request_id if valid_request_id(request_id) else None,
        "created_at": document["updated_at"],
    }
    pipeline.hset(OUTBOX_KEY, event_id, json.dumps(event))


def flush_failures(config: AppConfig, *, limit: int = 100) -> int:
    if not config.database_url:
        return 0
    try:
        with Redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=3) as connection:
            batch = list(islice(connection.hscan_iter(OUTBOX_KEY, count=limit), limit))
            if not batch:
                return 0
            with session_scope(config) as session:
                session.execute(text("""
                    INSERT INTO doctrace.document_failures
                        (id, workspace_id, owner_user_id, doc_id, job_id, attempt, kind,
                         error_code, request_id, created_at)
                    VALUES (CAST(:id AS uuid), CAST(:workspace_id AS uuid), CAST(:owner_user_id AS uuid),
                            CAST(:doc_id AS uuid), :job_id, :attempt, :kind, :error_code, :request_id,
                            CAST(:created_at AS timestamptz))
                    ON CONFLICT (id) DO NOTHING
                """), [json.loads(raw) for _, raw in batch])
            connection.hdel(OUTBOX_KEY, *(key for key, _ in batch))
            return len(batch)
    except Exception:
        logger.warning("failure_persistence_failed", exc_info=True)
        return 0


async def flush_failures_async(config: AppConfig) -> int:
    return await run_in_threadpool(flush_failures, config)
