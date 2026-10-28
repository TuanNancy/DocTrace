"""Linux integration worker: real Redis/RQ, fake PDF/embedding/S3/Milvus boundaries.

Only mounted by verify_document_queue.py; never copied into the production image.
"""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

from redis import Redis
from sqlalchemy import event, text

from app import db
from app.core.config import get_config
from app.jobs import documents
from app.services.document_repository import DocumentRepository
from app.services.pdf_indexing import InvalidPDFError
from app.worker import main

config = get_config()


def connection():
    return Redis.from_url(config.redis_url)


def download(key):
    return key.encode()


async def index(content, filename, generation, *, user_id, usage=None):
    doc_id = content.decode().split("/")[1]
    with connection() as redis:
        redis.set(f"vectors:{generation}", user_id)
        redis.set(f"started:{doc_id}", generation)
        if filename == "private-failure.pdf":
            raise RuntimeError("private-prompt-canary https://private.test/pdf?token=secret")
        if filename == "invalid.pdf":
            raise InvalidPDFError("no text")
        if filename == "retry.pdf" and redis.incr(f"failures:{doc_id}") == 1:
            raise ConnectionError("temporary embedding outage")
        timeout_once = filename == "timeout.pdf" and redis.incr(f"timeouts:{doc_id}") == 1
    if filename == "slow.pdf" or timeout_once:
        while True:
            with connection() as redis:
                if redis.exists(f"release:{doc_id}"):
                    break
            await asyncio.sleep(0.1)
    if usage:
        usage.start("index_embedding", "fixture-embedding").apply_usage({"prompt_tokens": 4, "cost": "0.000010"})
    return SimpleNamespace(chunks_count=3, warnings=[])


async def remove(user_id, generations):
    with connection() as redis:
        for generation in generations:
            owner = redis.get(f"vectors:{generation}")
            assert owner is None or owner.decode() == user_id
            redis.delete(f"vectors:{generation}")


def delete(key):
    doc_id = key.split("/")[1]
    with connection() as redis:
        if redis.get(f"fail-delete:{doc_id}") == b"yes":
            redis.delete(f"fail-delete:{doc_id}")
            raise ConnectionError("temporary storage outage")
        redis.set(f"deleted:{doc_id}", "yes")


original_finish = DocumentRepository.finish


async def finish(self, attempt, **kwargs):
    result = await original_finish(self, attempt, **kwargs)
    if result and attempt["document"]["name"] == "lost.pdf":
        raise ConnectionError("committed Redis response lost")
    return result


documents.download_pdf = download
documents.index_pdf_bytes = index
documents.remove_generations = remove
documents.delete_pdf = delete
if not config.database_url:
    documents.TranscriptService = lambda config: SimpleNamespace(hide_for_document=AsyncMock(return_value=0))
else:
    # Deliberately populate the parent's pool before any fork. Without the
    # worker's child reset, metering/retention fails instead of reusing sockets.
    engine = db.get_engine(config)
    @event.listens_for(engine, "connect")
    def connected(connection, record):
        record.info["pid"] = os.getpid()

    @event.listens_for(engine, "checkout")
    def checked_out(connection, record, proxy):
        assert record.info["pid"] == os.getpid(), "Inherited PostgreSQL connection"

    with engine.connect() as sql:
        sql.execute(text("SELECT 1"))
DocumentRepository.finish = finish

if __name__ == "__main__":
    main()
