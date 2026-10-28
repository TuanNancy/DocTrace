"""Exact, generation-aware answer cache on a Redis instance separate from RQ.

Only complete successful answers with valid citations are stored. The key binds
the workspace, owner, document, active index generation, prompt version,
retrieval settings and routed model, so a re-index or policy change can never
reuse an old answer. A deleted document is already unavailable before any
lookup. Cache failures are a miss, never a chat failure.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from typing import Optional

from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry
from starlette.concurrency import run_in_threadpool

from app.core.config import AppConfig, get_config

PREFIX = "doctrace:answer-cache:v1"
SCHEMA_VERSION = 1
MAX_ANSWER_CHARS = 100_000
MAX_SOURCES = 100
_CITATION = re.compile(r"\[(\d+)\]")
logger = logging.getLogger(__name__)


def normalize_query(value: str) -> str:
    """NFC/NFKC + casefold + whitespace collapse; meaning is never rewritten."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def cache_key(
    *, workspace_id: str, user_id: str, doc_id: str, index_id: str,
    query: str, language: str, model: str, prompt_version: str,
    retrieval_top_k: int, min_relevance_score: float, context_max_chars: int,
    max_tokens: int, temperature: float, summary_max_calls: int, overview: bool,
) -> str:
    fields = {
        "schema": SCHEMA_VERSION,
        "workspace_id": workspace_id, "user_id": user_id, "doc_id": doc_id,
        "index_id": index_id, "query": normalize_query(query), "language": language,
        "model": model, "prompt_version": prompt_version,
        "retrieval_top_k": retrieval_top_k, "min_relevance_score": min_relevance_score,
        "context_max_chars": context_max_chars, "max_tokens": max_tokens,
        "temperature": temperature, "summary_max_calls": summary_max_calls,
        "overview": overview,
    }
    digest = hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"{PREFIX}:answer:{digest}"


def _valid_sources(value) -> bool:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_SOURCES:
        return False
    for source in value:
        if not isinstance(source, dict):
            return False
        if type(source.get("citation_id")) is not int or source["citation_id"] < 1:
            return False
        if not isinstance(source.get("chunk_id"), str) or not isinstance(source.get("doc_id"), str):
            return False
        if type(source.get("page")) is not int or source["page"] < 1:
            return False
        if not isinstance(source.get("source"), str):
            return False
        score = source.get("score")
        if score is not None and not isinstance(score, (int, float)):
            return False
    return [source["citation_id"] for source in value] == list(range(1, len(value) + 1))


def _valid_citations(answer: str, sources: list[dict]) -> bool:
    numbers = {int(match.group(1)) for match in _CITATION.finditer(answer)}
    return bool(numbers) and all(1 <= number <= len(sources) for number in numbers)


def valid_payload(value, *, doc_id: Optional[str] = None) -> Optional[dict]:
    if not isinstance(value, dict):
        return None
    answer, sources = value.get("answer"), value.get("sources")
    if not isinstance(answer, str) or not answer.strip() or len(answer) > MAX_ANSWER_CHARS:
        return None
    if not _valid_sources(sources):
        return None
    if not _valid_citations(answer, sources):
        return None
    if doc_id is not None and any(source["doc_id"] != doc_id for source in sources):
        return None
    return {"answer": answer, "sources": sources}


class AnswerCache:
    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or get_config()
        self.url = self.config.answer_cache_url
        self.ttl = self.config.answer_cache_ttl_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def _connection(self) -> Redis:
        # Cache latency must never become chat latency.
        return Redis.from_url(
            self.url, socket_connect_timeout=1, socket_timeout=1,
            retry=Retry(NoBackoff(), 0),
        )

    def _get(self, key: str, doc_id: Optional[str]) -> Optional[dict]:
        with self._connection() as connection:
            raw = connection.get(key)
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return valid_payload(payload, doc_id=doc_id)

    async def get(self, key: str, *, doc_id: Optional[str] = None) -> Optional[dict]:
        if not self.enabled:
            return None
        try:
            return await run_in_threadpool(self._get, key, doc_id)
        except RedisError:
            logger.warning("answer_cache_failed")
            return None

    def _put(self, key: str, payload: dict) -> None:
        with self._connection() as connection:
            connection.set(key, json.dumps(payload, separators=(",", ":")), ex=self.ttl)

    async def put(self, key: str, payload: dict) -> None:
        if not self.enabled:
            return
        clean = valid_payload(payload)
        if clean is None:
            return
        try:
            await run_in_threadpool(self._put, key, clean)
        except RedisError:
            logger.warning("answer_cache_failed")


def get_answer_cache() -> AnswerCache:
    return AnswerCache(get_config())
