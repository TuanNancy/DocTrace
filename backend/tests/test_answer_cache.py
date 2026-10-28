"""Exact-answer cache: policy-bound keys, validation, TTL and fail-open reads."""
import asyncio
import json

import fakeredis
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import AppConfig
from app.services.answer_cache import AnswerCache, cache_key, normalize_query, valid_payload


def key(**overrides):
    values = {
        "workspace_id": "w", "user_id": "u", "doc_id": "d", "index_id": "g1",
        "query": "How much leave?", "language": "en", "model": "model-a",
        "prompt_version": "prompt-v1", "retrieval_top_k": 8,
        "min_relevance_score": 0.32, "context_max_chars": 12000, "max_tokens": 2048,
        "temperature": 0.7, "summary_max_calls": 8, "overview": False,
    }
    values.update(overrides)
    return cache_key(**values)


def sources(doc_id="d"):
    return [{"citation_id": 1, "chunk_id": "c1", "doc_id": doc_id,
             "page": 2, "source": "policy.pdf", "score": 0.9}]


def test_normalized_query_and_policy_versions_change_the_key():
    assert normalize_query("  How\tmuch   LEAVE? ") == "how much leave?"
    base = key()
    assert base == key(query="how much leave?")
    assert base != key(index_id="g2")
    assert base != key(index_id="g1", model="model-b")
    assert base != key(prompt_version="prompt-v2")
    assert base != key(retrieval_top_k=4)
    assert base != key(context_max_chars=8000)
    assert base != key(temperature=0.0)
    assert base != key(summary_max_calls=4)
    assert base != key(overview=True)
    assert base.startswith("doctrace:answer-cache:v1:answer:")


def test_cache_round_trip_sets_ttl_and_rejects_wrong_document(monkeypatch):
    redis = fakeredis.FakeRedis()
    cache = AnswerCache(AppConfig(answer_cache_url="redis://cache.test:6379/0",
                                  answer_cache_ttl_seconds=120))
    monkeypatch.setattr(cache, "_connection", lambda: redis)
    payload = {"answer": "Twelve days [1].", "sources": sources()}

    asyncio.run(cache.put("k", payload))
    assert asyncio.run(cache.get("k", doc_id="d")) == payload
    assert redis.ttl("k") == 120
    assert asyncio.run(cache.get("k", doc_id="other")) is None


@pytest.mark.parametrize("payload", [
    {"answer": "", "sources": sources()},
    {"answer": "answer", "sources": []},
    {"answer": "answer without a citation", "sources": sources()},
    {"answer": "answer [2]", "sources": sources()},
    {"answer": "answer", "sources": [{**sources()[0], "citation_id": 2}]},
    {"answer": "answer [1]", "sources": [{"citation_id": 1, "chunk_id": "c", "doc_id": "d",
                                          "page": 0, "source": "s", "score": None}]},
])
def test_invalid_payload_is_never_served(payload):
    assert valid_payload(payload) is None


def test_corrupt_or_wrong_document_payload_is_a_miss(monkeypatch):
    redis = fakeredis.FakeRedis()
    cache = AnswerCache(AppConfig(answer_cache_url="redis://cache.test:6379/0"))
    monkeypatch.setattr(cache, "_connection", lambda: redis)
    redis.set("corrupt", "{")
    redis.set("wrong", json.dumps({"answer": "a [1]", "sources": sources("other")}))

    assert asyncio.run(cache.get("corrupt", doc_id="d")) is None
    assert asyncio.run(cache.get("wrong", doc_id="d")) is None


def test_cache_errors_are_misses_and_disabled_cache_does_not_connect(monkeypatch):
    cache = AnswerCache(AppConfig(answer_cache_url="redis://cache.test:6379/0"))
    monkeypatch.setattr(cache, "_connection", lambda: (_ for _ in ()).throw(RedisConnectionError("down")))
    assert asyncio.run(cache.get("k", doc_id="d")) is None
    asyncio.run(cache.put("k", {"answer": "a [1]", "sources": sources()}))

    disabled = AnswerCache(AppConfig())
    monkeypatch.setattr(disabled, "_connection", lambda: (_ for _ in ()).throw(AssertionError("no connect")))
    assert asyncio.run(disabled.get("k")) is None
    asyncio.run(disabled.put("k", {"answer": "a [1]", "sources": sources()}))
