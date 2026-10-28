"""Backfill workspace metadata for documents catalogued before P1.

Safe to re-run: personal workspaces and Redis sorted sets are written
idempotently, and the legacy per-user index is retained. The default is a dry
run; pass ``--apply`` to write. This script never flushes Redis or touches
Milvus.

Usage:
    cd backend && python scripts/backfill_workspaces.py --apply
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import logging
import sys
from pathlib import Path
from uuid import UUID

from redis import Redis
from redis.exceptions import WatchError
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import AppConfig, get_config  # noqa: E402
from app.db import DatabaseNotConfigured, session_scope  # noqa: E402
from app.services.document_repository import (  # noqa: E402
    PREFIX, document_key, global_key, legacy_user_key, workspace_key, workspace_user_key,
)

logger = logging.getLogger("backfill_workspaces")

PERSONAL_WORKSPACE_SQL = text(
    """
    INSERT INTO doctrace.workspaces
        (id, name, kind, plan, created_by, personal_owner_user_id)
    VALUES (:uid, :name, 'personal', 'free', :uid, :uid)
    ON CONFLICT (id) DO NOTHING
    """
)
PERSONAL_MEMBER_SQL = text(
    """
    INSERT INTO doctrace.workspace_members (workspace_id, user_id, role, status)
    VALUES (:uid, :uid, 'owner', 'active')
    ON CONFLICT (workspace_id, user_id) DO NOTHING
    """
)


def iter_documents(connection: Redis, batch_size: int = 500):
    """Yield decoded catalog records; the key's suffix repairs a missing doc_id."""
    for raw_key in connection.scan_iter(match=f"{PREFIX}:document:*", count=batch_size):
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        raw = connection.hget(key, "data")
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("Skipping unreadable catalog record %s", key)
            continue
        if not isinstance(record, dict):
            logger.warning("Skipping non-object catalog record %s", key)
            continue
        record["doc_id"] = key.rsplit(":", 1)[-1]
        yield record


def normalize_record(record: dict) -> tuple[dict | None, bool]:
    """Return (record with workspace fields, whether the hash must be rewritten).

    ``user_id`` is authoritative because Milvus chunks and RQ retries use it.
    Missing workspace metadata maps to the owner's personal workspace.
    """
    owner = record.get("user_id") or record.get("owner_user_id")
    doc_id = record.get("doc_id")
    if not owner or not doc_id:
        return None, False
    workspace = record.get("workspace_id") or owner
    changed = (
        record.get("owner_user_id") != owner
        or record.get("workspace_id") != workspace
    )
    return {**record, "owner_user_id": owner, "workspace_id": workspace}, changed


def score_for(record: dict) -> float:
    try:
        value = datetime.fromisoformat(record["created_at"])
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    except (KeyError, TypeError, ValueError):
        return 0  # Stable ordering for legacy records without a usable timestamp.


def repair_document(connection: Redis, doc_id: str, *, apply: bool) -> Counter:
    """Repair one current record, never the snapshot read by SCAN.

    Workers change the hash and its indexes in one transaction. Watching that
    hash fences both metadata normalization and index repair against a concurrent
    publication/deletion. Tombstones are retained but removed from all indexes.
    """
    key = document_key(doc_id)
    for _ in range(10):
        with connection.pipeline() as pipe:
            try:
                pipe.watch(key)
                raw = pipe.hget(key, "data")
                if not raw:
                    return Counter(skipped_missing=1)
                try:
                    record = json.loads(raw)
                except (TypeError, ValueError):
                    return Counter(skipped_invalid=1)
                if not isinstance(record, dict):
                    return Counter(skipped_invalid=1)
                normalized, changed = normalize_record({**record, "doc_id": doc_id})
                if normalized is None:
                    return Counter(skipped_invalid=1)
                changed = changed or record.get("doc_id") != doc_id
                workspace_id, owner = normalized["workspace_id"], normalized["owner_user_id"]
                indexes = (
                    workspace_user_key(workspace_id, owner), workspace_key(workspace_id),
                    global_key(), legacy_user_key(owner),
                )
                deleted = normalized.get("status") == "deleted"
                present = sum(pipe.zscore(index, doc_id) is not None for index in indexes)
                stats = Counter({
                    "hashes_updated" if changed else "hashes_unchanged": 1,
                    "index_entries_planned": len(indexes),
                    "index_entries_added": 0 if deleted else len(indexes) - present,
                    "index_entries_removed": present if deleted else 0,
                    "deleted_records": int(deleted),
                })
                if apply:
                    pipe.multi()
                    if changed:
                        pipe.hset(key, "data", json.dumps(normalized))
                    for index in indexes:
                        if deleted:
                            pipe.zrem(index, doc_id)
                        else:
                            pipe.zadd(index, {doc_id: score_for(normalized)})
                    pipe.execute()
                return stats
            except WatchError:
                continue
    raise RuntimeError(f"Catalog record {doc_id} kept changing; rerun the backfill")


def provision_personal_workspaces(config: AppConfig, owners: list[str], *, apply: bool) -> int:
    """Create the demo personal workspace/membership for idempotent backfill."""
    valid = []
    for owner in owners:
        try:
            UUID(owner)
        except (TypeError, ValueError):
            logger.warning("Skipping personal workspace for non-UUID owner %r", owner)
            continue
        valid.append(owner)
    if not apply:
        return len(valid)
    try:
        for start in range(0, len(valid), 200):
            with session_scope(config) as session:
                for owner in valid[start:start + 200]:
                    session.execute(PERSONAL_WORKSPACE_SQL, {"uid": owner, "name": "Cá nhân"})
                    session.execute(PERSONAL_MEMBER_SQL, {"uid": owner})
    except DatabaseNotConfigured as exc:
        raise SystemExit("DATABASE_URL is required for --apply") from exc
    return len(valid)


def run(connection: Redis, config: AppConfig, *, apply: bool, batch_size: int = 500) -> dict:
    """Scan, normalize and (optionally) write; reruns are safe."""
    stats: Counter = Counter()
    personal_owners: set[str] = set()

    # Collect owners first so Postgres provisioning happens before Redis writes.
    for record in iter_documents(connection, batch_size):
        stats["scanned"] += 1
        normalized, _ = normalize_record(record)
        if normalized is None:
            continue
        if normalized["workspace_id"] == normalized["owner_user_id"]:
            personal_owners.add(normalized["owner_user_id"])

    stats["personal_workspaces"] = provision_personal_workspaces(
        config, sorted(personal_owners), apply=apply,
    )

    for record in iter_documents(connection, batch_size):
        stats.update(repair_document(connection, record["doc_id"], apply=apply))

    return {key: stats[key] for key in (
        "scanned", "personal_workspaces", "hashes_updated", "hashes_unchanged",
        "index_entries_planned", "index_entries_added", "index_entries_removed",
        "deleted_records", "skipped_invalid", "skipped_missing",
    )}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write updates (default: dry run)")
    parser.add_argument("--batch-size", type=int, default=500, help="Redis SCAN count")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = get_config()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    with Redis.from_url(config.redis_url, socket_connect_timeout=5, socket_timeout=30) as connection:
        connection.ping()
        stats = run(connection, config, apply=args.apply, batch_size=args.batch_size)
    mode = "APPLIED" if args.apply else "DRY RUN (pass --apply to write)"
    print(json.dumps({"mode": mode, **stats}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
