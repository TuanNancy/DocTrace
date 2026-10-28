"""Idempotent workspace backfill: dry run, normalization and index repair."""
import importlib.util
import json
from pathlib import Path

import fakeredis
import pytest
from redis.client import Pipeline

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/backfill_workspaces.py"
spec = importlib.util.spec_from_file_location("backfill_workspaces", MODULE_PATH)
backfill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backfill)

from app.core.config import AppConfig  # noqa: E402
from app.services.document_repository import (  # noqa: E402
    document_key, global_key, legacy_user_key, workspace_key, workspace_user_key,
)

OWNER = "00000000-0000-0000-0000-000000000001"
TEAM = "00000000-0000-0000-0000-0000000000cd"
LEGACY_DOC = "10000000-0000-0000-0000-000000000001"
TEAM_DOC = "10000000-0000-0000-0000-000000000002"


def seed(connection):
    connection.hset(document_key(LEGACY_DOC), "data", json.dumps({
        "doc_id": LEGACY_DOC, "user_id": OWNER, "name": "old.pdf", "size_bytes": 10,
        "storage_key": "old.pdf", "status": "ready", "chunks_count": 1, "warnings": [],
        "error": None, "created_at": "2026-01-02T03:04:05+00:00",
        "updated_at": "2026-01-02T03:04:05+00:00", "active_index_id": "generation",
        "job_id": "index-old", "job_kind": "index", "attempt_number": 1,
        "attempt_id": "generation", "generations": ["generation"],
    }))
    connection.zadd(legacy_user_key(OWNER), {LEGACY_DOC: 1})
    connection.hset(document_key(TEAM_DOC), "data", json.dumps({
        "doc_id": TEAM_DOC, "user_id": OWNER, "workspace_id": TEAM,
        "name": "team.pdf", "status": "ready", "created_at": "not-a-date",
    }))


def no_database(config, owners, *, apply):
    return len(owners)


def test_dry_run_never_writes_redis_or_postgres(monkeypatch):
    connection = fakeredis.FakeRedis()
    seed(connection)
    before = connection.hget(document_key(LEGACY_DOC), "data")
    monkeypatch.setattr(backfill, "provision_personal_workspaces", no_database)

    stats = backfill.run(connection, AppConfig(), apply=False)

    assert stats["scanned"] == 2
    assert stats["hashes_updated"] == 2
    assert stats["personal_workspaces"] == 1
    assert connection.hget(document_key(LEGACY_DOC), "data") == before
    assert connection.zcard(workspace_key(TEAM)) == 0


def test_apply_normalizes_hashes_and_rebuilds_every_index(monkeypatch):
    connection = fakeredis.FakeRedis()
    seed(connection)
    monkeypatch.setattr(backfill, "provision_personal_workspaces", no_database)

    stats = backfill.run(connection, AppConfig(), apply=True)

    assert stats["hashes_updated"] == 2
    legacy = json.loads(connection.hget(document_key(LEGACY_DOC), "data"))
    assert (legacy["owner_user_id"], legacy["workspace_id"]) == (OWNER, OWNER)
    team = json.loads(connection.hget(document_key(TEAM_DOC), "data"))
    assert (team["owner_user_id"], team["workspace_id"]) == (OWNER, TEAM)
    for index in (
        workspace_user_key(OWNER, OWNER), workspace_key(OWNER), global_key(), legacy_user_key(OWNER),
    ):
        assert connection.zscore(index, LEGACY_DOC) is not None
    for index in (
        workspace_user_key(TEAM, OWNER), workspace_key(TEAM), global_key(), legacy_user_key(OWNER),
    ):
        assert connection.zscore(index, TEAM_DOC) is not None

    again = backfill.run(connection, AppConfig(), apply=True)
    assert again["hashes_updated"] == 0
    assert again["hashes_unchanged"] == 2
    assert connection.zcard(global_key()) == 2


def test_records_without_an_owner_or_doc_id_are_skipped():
    connection = fakeredis.FakeRedis()
    connection.hset(document_key("no-owner"), "data", json.dumps({"doc_id": "no-owner"}))
    connection.hset("doctrace:library:v2:document:broken", "data", "not-json")
    stats = backfill.run(connection, AppConfig(), apply=False)
    assert stats["scanned"] == 1
    assert stats["skipped_invalid"] == 1
    assert stats["hashes_updated"] == 0


def indexes():
    return (workspace_user_key(OWNER, OWNER), workspace_key(OWNER), global_key(), legacy_user_key(OWNER))


@pytest.mark.parametrize("status", ["ready", "error", "delete_error", "deleting", "deleted"])
def test_backfill_repairs_counts_without_resurrecting_deleted_documents(monkeypatch, status):
    connection = fakeredis.FakeRedis()
    seed(connection)
    record = json.loads(connection.hget(document_key(LEGACY_DOC), "data"))
    record.update(workspace_id=OWNER, owner_user_id=OWNER, status=status)
    connection.hset(document_key(LEGACY_DOC), "data", json.dumps(record))
    for key in indexes():
        connection.zadd(key, {LEGACY_DOC: 1})
    monkeypatch.setattr(backfill, "provision_personal_workspaces", no_database)

    dry = backfill.run(connection, AppConfig(), apply=False)
    assert dry["index_entries_removed"] == (4 if status == "deleted" else 0)
    assert all(connection.zscore(key, LEGACY_DOC) is not None for key in indexes())
    backfill.run(connection, AppConfig(), apply=True)
    again = backfill.run(connection, AppConfig(), apply=True)
    assert again["hashes_updated"] == 0
    assert again["index_entries_added"] == again["index_entries_removed"] == 0
    assert all((connection.zscore(key, LEGACY_DOC) is None) == (status == "deleted") for key in indexes())
    assert json.loads(connection.hget(document_key(LEGACY_DOC), "data"))["status"] == status


@pytest.mark.parametrize("outcome", ["ready", "deleted", "missing"])
def test_backfill_retries_against_current_worker_state(monkeypatch, outcome):
    connection = fakeredis.FakeRedis()
    seed(connection)
    key = document_key(LEGACY_DOC)
    original = Pipeline.execute
    raced = False

    def execute(pipe, *args, **kwargs):
        nonlocal raced
        if not raced and any(command[0][0] == "HSET" and command[0][1] == key
                             for command in pipe.command_stack):
            raced = True
            current = json.loads(connection.hget(key, "data"))
            current.update(status=outcome, active_index_id="new-generation", job_id="new-job",
                           attempt_id="new-generation", generations=["old-generation", "new-generation"])
            if outcome == "missing":
                connection.delete(key)
            else:
                connection.hset(key, "data", json.dumps(current))
            if outcome == "deleted":
                for index in indexes():
                    connection.zrem(index, LEGACY_DOC)
        return original(pipe, *args, **kwargs)

    monkeypatch.setattr(Pipeline, "execute", execute)
    monkeypatch.setattr(backfill, "provision_personal_workspaces", no_database)
    stats = backfill.run(connection, AppConfig(), apply=True)
    assert raced
    if outcome == "missing":
        assert not connection.exists(key)
        assert stats["skipped_missing"] == 1
    else:
        current = json.loads(connection.hget(key, "data"))
        assert current["status"] == outcome
        assert current["job_id"] == "new-job"
        assert current["active_index_id"] == "new-generation"
        assert current["generations"] == ["old-generation", "new-generation"]
        assert all((connection.zscore(index, LEGACY_DOC) is None) == (outcome == "deleted")
                   for index in indexes())
