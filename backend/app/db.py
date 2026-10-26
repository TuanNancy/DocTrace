"""Control-plane Postgres access and dependency probes.

The document catalog and queue stay in Redis. This module owns only the
Postgres control plane: workspace membership, plans, usage, transcripts and
audit events. Calls are synchronous and must run off the event loop, matching
the existing Redis/S3/Milvus boundary.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from threading import Lock
from time import perf_counter
from typing import Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.core.config import AppConfig, get_config

logger = logging.getLogger(__name__)

POSTGRES_SCHEMES = ("postgres", "postgresql", "postgresql+psycopg")
SCHEMA = "doctrace"

_engine: Optional[Engine] = None
_engine_key: Optional[tuple] = None
_session_factory: Optional[sessionmaker] = None
_lock = Lock()


class DatabaseNotConfigured(RuntimeError):
    """Raised when a feature needs Postgres but DATABASE_URL is unset."""


def normalize_database_url(url: str) -> str:
    """Use psycopg 3 without rewriting credentials or query parameters."""
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    raise ValueError("DATABASE_URL must be a PostgreSQL URL")


def _engine_key_for(config: AppConfig, url: str) -> tuple:
    return (
        url,
        config.database_pool_size,
        config.database_pool_max_overflow,
        config.database_pool_timeout_seconds,
        config.database_connect_timeout_seconds,
        config.database_statement_timeout_ms,
    )


def _connect_args(config: AppConfig) -> dict:
    return {
        "connect_timeout": max(1, round(config.database_connect_timeout_seconds)),
        "application_name": "doctrace",
        "options": f"-c statement_timeout={config.database_statement_timeout_ms}",
        # Supabase's transaction pooler does not support cached prepared
        # statements. Disabling the cache is safe for direct connections too.
        "prepare_threshold": None,
    }


def get_engine(config: Optional[AppConfig] = None) -> Engine:
    """Return the process-wide pooled engine for DATABASE_URL."""
    global _engine, _engine_key, _session_factory
    config = config or get_config()
    if not config.database_url:
        raise DatabaseNotConfigured("DATABASE_URL is not configured")
    url = normalize_database_url(config.database_url)
    key = _engine_key_for(config, url)
    with _lock:
        if _engine is None or _engine_key != key:
            if _engine is not None:
                _engine.dispose()
            _engine = create_engine(
                url,
                pool_pre_ping=True,
                pool_size=config.database_pool_size,
                max_overflow=config.database_pool_max_overflow,
                pool_timeout=config.database_pool_timeout_seconds,
                pool_recycle=1800,
                connect_args=_connect_args(config),
            )
            _engine_key = key
            _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
        return _engine


def get_sessionmaker(config: Optional[AppConfig] = None) -> sessionmaker:
    get_engine(config)
    assert _session_factory is not None
    return _session_factory


@contextmanager
def session_scope(config: Optional[AppConfig] = None) -> Iterator[Session]:
    """Commit on success, roll back on any exception, always close."""
    session = get_sessionmaker(config)()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engines() -> None:
    """Release pooled connections on shutdown or after config changes."""
    global _engine, _engine_key, _session_factory
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _engine_key = None
        _session_factory = None


def _ping_database(config: AppConfig) -> None:
    engine = get_engine(config)
    with engine.connect() as connection:
        migrated = connection.execute(
            text("SELECT to_regclass(:relation) IS NOT NULL"),
            {"relation": f"{SCHEMA}.workspaces"},
        ).scalar()
    if not migrated:
        raise RuntimeError("doctrace schema is not migrated")


async def check_database(config: Optional[AppConfig] = None) -> dict:
    """Short dependency probe for /ready; never raises."""
    config = config or get_config()
    if not config.database_url:
        return {"status": "disabled", "latency_ms": None}
    started = perf_counter()
    try:
        await run_in_threadpool(_ping_database, config)
    except Exception:
        logger.warning("Database readiness probe failed", exc_info=True)
        return {
            "status": "error",
            "latency_ms": round((perf_counter() - started) * 1000),
            "error_code": "database_unavailable",
        }
    return {"status": "ok", "latency_ms": round((perf_counter() - started) * 1000)}
