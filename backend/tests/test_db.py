"""Postgres URL handling and readiness probes without a live database."""
from dataclasses import replace
from pathlib import Path

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


async def test_database_probe_bounds_but_tolerates_slow_hosted_pooler(monkeypatch):
    captured = {}

    class ProbeEngine:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        def connect(self):
            raise RuntimeError("probe configuration only")

        def dispose(self):
            pass

    monkeypatch.setattr(db, "create_engine", ProbeEngine)
    result = await db.check_database(AppConfig(database_url="postgresql://u:p@db.test/app"))
    assert result["status"] == "error"
    assert captured["connect_args"]["connect_timeout"] == 5
    assert "statement_timeout=5000" in captured["connect_args"]["options"]
    assert "lock_timeout=2000" in captured["connect_args"]["options"]


async def test_database_probe_fails_closed_without_config_or_on_failure(monkeypatch):
    assert (await db.check_database(AppConfig())) == {
        "status": "error", "latency_ms": None, "error_code": "database_not_configured",
    }

    def fail(config):
        raise RuntimeError("private host detail")

    monkeypatch.setattr(db, "_ping_database", fail)
    result = await db.check_database(AppConfig(database_url="postgresql://u:p@db.test/app"))
    assert result["status"] == "error"
    assert result["error_code"] == "database_unavailable"
    assert "private" not in str(result)


def test_runtime_engine_never_formats_sql_parameters():
    db.dispose_engines()
    try:
        engine = db.get_engine(AppConfig(database_url="postgresql://u:p@db.test/app"))
        assert engine.hide_parameters is True
    finally:
        db.dispose_engines()


def test_migrations_do_not_fall_back_to_runtime_credentials(monkeypatch):
    from alembic import command
    from alembic.config import Config
    monkeypatch.delenv("DIRECT_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://runtime:private@db.test/app")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with pytest.raises(RuntimeError, match="DIRECT_DATABASE_URL is required"):
        command.upgrade(config, "head")
