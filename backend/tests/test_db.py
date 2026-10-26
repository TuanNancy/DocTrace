"""Postgres URL handling and readiness probes without a live database."""
from dataclasses import replace

import pytest

from app import db
from app.core.config import AppConfig


def test_database_urls_are_normalized_for_psycopg3():
    assert (db.normalize_database_url("postgres://u:p@db.test/app")
            == "postgresql+psycopg://u:p@db.test/app")
    assert (db.normalize_database_url("postgresql://u:p@db.test/app?sslmode=require")
            == "postgresql+psycopg://u:p@db.test/app?sslmode=require")
    assert (db.normalize_database_url("postgresql+psycopg://u:p@db.test/app")
            == "postgresql+psycopg://u:p@db.test/app")
    with pytest.raises(ValueError, match="PostgreSQL"):
        db.normalize_database_url("mysql://u:p@db.test/app")


def test_engine_requires_database_url():
    db.dispose_engines()
    with pytest.raises(db.DatabaseNotConfigured):
        db.get_engine(AppConfig())


def test_connect_arguments_bound_statements_and_pooler_compatibility():
    config = AppConfig(
        database_url="postgresql://u:p@db.test/app",
        database_pool_size=3, database_pool_max_overflow=2,
        database_pool_timeout_seconds=1.5, database_connect_timeout_seconds=2.4,
        database_statement_timeout_ms=4000,
    )
    args = db._connect_args(config)
    assert args["connect_timeout"] == 2
    assert args["prepare_threshold"] is None
    assert args["options"] == "-c statement_timeout=4000"
    assert db._engine_key_for(config, "postgresql+psycopg://u:p@db.test/app")[1:3] == (3, 2)
    assert replace(config, database_pool_size=4) != config


async def test_database_probe_is_disabled_or_bounded(monkeypatch):
    assert (await db.check_database(AppConfig()))["status"] == "disabled"

    def fail(config):
        raise RuntimeError("private host detail")

    monkeypatch.setattr(db, "_ping_database", fail)
    result = await db.check_database(AppConfig(database_url="postgresql://u:p@db.test/app"))
    assert result["status"] == "error"
    assert result["error_code"] == "database_unavailable"
    assert "private" not in str(result)
