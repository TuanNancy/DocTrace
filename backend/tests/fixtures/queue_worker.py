"""Linux integration worker: real Redis/RQ, fake PDF/embedding/S3/Milvus boundaries.

Only mounted by verify_document_queue.py; never copied into the production image.
"""
import asyncio
from types import SimpleNamespace

from redis import Redis

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


async def index(content, filename, generation, *, user_id):
    doc_id = content.decode().split("/")[1]
    with connection() as redis:
        redis.set(f"vectors:{generation}", user_id)
        redis.set(f"started:{doc_id}", generation)
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
DocumentRepository.finish = finish

if __name__ == "__main__":
    main()
