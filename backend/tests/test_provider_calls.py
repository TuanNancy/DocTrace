"""Usage collector persistence, reconciliation and best-effort failure handling."""
from contextlib import contextmanager
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.providers import openrouter
from app.services import provider_calls
from app.services.provider_calls import UsageAttribution, UsageCollector, _uuid_or_none


class _Session:
    def __init__(self):
        self.rows = []
        self.statements = []

    def execute(self, statement, rows):
        self.statements.append(statement)
        self.rows.extend(rows)


@contextmanager
def _scope(session):
    yield session


def _enabled_config(**overrides):
    values = {"database_url": "postgresql://example.test/doctrace", "openrouter_api_key": None}
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def session(monkeypatch):
    fake = _Session()
    monkeypatch.setattr(provider_calls, "session_scope", lambda config: _scope(fake))
    return fake


def test_disabled_collector_starts_no_calls_and_flushes_nothing(session):
    collector = UsageCollector(
        UsageAttribution(), config=SimpleNamespace(database_url=None),
    )
    assert collector.start("answer", "model") is None
    assert collector.calls == []


async def test_collector_persists_each_call_with_attribution(session):
    workspace, user, doc, request = (str(uuid4()) for _ in range(4))
    collector = UsageCollector(
        UsageAttribution(
            workspace_id=workspace, user_id=user, doc_id=doc,
            job_id="job-1", request_id=request,
        ),
        config=_enabled_config(),
    )
    answer = collector.start("answer", "chat-model")
    answer.apply_usage({
        "prompt_tokens": 10, "completion_tokens": 5,
        "cached_tokens": 3, "reasoning_tokens": 2, "cost": "0.000123",
    })
    answer.generation_id = "gen-answer"
    summary = collector.start("summary", "chat-model")
    summary.apply_usage({"prompt_tokens": 4, "completion_tokens": 1})
    summary.generation_id = "gen-summary"

    await collector.flush()

    assert len(session.rows) == 2
    first, second = session.rows
    assert first["kind"] == "answer"
    assert first["workspace_id"] == workspace
    assert first["user_id"] == user
    assert first["doc_id"] == doc
    assert first["request_id"] == request
    assert first["job_id"] == "job-1"
    assert first["prompt_tokens"] == 10
    assert first["completion_tokens"] == 5
    assert first["cached_tokens"] == 3
    assert first["reasoning_tokens"] == 2
    assert first["cost_micros"] == 123
    assert first["cost_status"] == "reported"
    assert second["kind"] == "summary"
    assert second["cost_micros"] is None
    assert second["cost_status"] == "unknown"
    assert "ON CONFLICT (generation_id)" in str(session.statements[0])


async def test_flush_is_idempotent(session):
    collector = UsageCollector(UsageAttribution(), config=_enabled_config())
    collector.start("answer", "model").apply_usage({"cost": "0.000002"})

    await collector.flush()
    await collector.flush()

    assert len(session.rows) == 1


async def test_missing_cost_is_reconciled_by_generation(session, monkeypatch):
    collector = UsageCollector(
        UsageAttribution(), config=_enabled_config(openrouter_api_key="key"),
    )
    call = collector.start("answer", "model")
    call.apply_usage({"prompt_tokens": 8, "completion_tokens": 2})
    call.generation_id = "gen-1"

    async def generation(config, generation_id):
        assert generation_id == "gen-1"
        return {"id": "gen-1", "total_cost": "0.00005", "tokens_prompt": 8}

    monkeypatch.setattr(openrouter, "fetch_generation", generation)

    await collector.flush()

    assert call.cost_micros == 50
    assert call.cost_status == "reconciled"
    assert call.prompt_tokens == 8
    assert session.rows[0]["cost_micros"] == 50
    assert session.rows[0]["cost_status"] == "reconciled"
    assert json.loads(session.rows[0]["raw_usage"])["generation"]["total_cost"] == "0.00005"


async def test_reconciliation_failure_never_blocks_persistence(session, monkeypatch):
    collector = UsageCollector(
        UsageAttribution(), config=_enabled_config(openrouter_api_key="key"),
    )
    call = collector.start("summary", "model")
    call.generation_id = "gen-1"

    async def generation(config, generation_id):
        raise ConnectionError("lookup unavailable")

    monkeypatch.setattr(openrouter, "fetch_generation", generation)

    await collector.flush()

    assert call.cost_micros is None
    assert call.cost_status == "unknown"
    assert len(session.rows) == 1
    assert session.rows[0]["cost_micros"] is None


async def test_persistence_failure_is_best_effort(monkeypatch):
    collector = UsageCollector(UsageAttribution(), config=_enabled_config())
    collector.start("answer", "model").apply_usage({"cost": "0.000001"})

    def fail(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(provider_calls, "run_in_threadpool", fail)

    await collector.flush()  # Must not raise into the chat/index request.

    assert collector._flushed is True


async def test_store_failure_inside_threadpool_is_swallowed(monkeypatch):
    collector = UsageCollector(UsageAttribution(), config=_enabled_config())
    collector.start("answer", "model")

    @contextmanager
    def broken_scope(config):
        raise RuntimeError("database unavailable")
        yield  # pragma: no cover

    monkeypatch.setattr(provider_calls, "session_scope", broken_scope)

    await collector.flush()


async def test_malformed_attribution_is_dropped_instead_of_failing(session):
    collector = UsageCollector(
        UsageAttribution(
            workspace_id="not-a-uuid", user_id="also-bad", doc_id="doc",
            job_id="job", request_id="request",
        ),
        config=_enabled_config(),
    )
    collector.start("answer", "model").apply_usage({"prompt_tokens": 1})

    await collector.flush()

    row = session.rows[0]
    assert row["workspace_id"] is None
    assert row["user_id"] is None
    assert row["doc_id"] is None
    assert row["request_id"] is None
    assert row["job_id"] == "job"


def test_uuid_normalization_handles_uppercase_braces_and_none():
    valid = uuid4()
    assert _uuid_or_none(str(valid).upper()) == str(valid)
    assert _uuid_or_none(f"{{{valid}}}") == str(valid)
    assert _uuid_or_none(None) is None
    assert _uuid_or_none("") is None
    assert _uuid_or_none("not-a-uuid") is None
