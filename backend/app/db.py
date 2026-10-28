"""Control-plane Postgres access and dependency probes.

The document catalog and queue stay in Redis. This module owns only the
Postgres control plane: workspace membership, plans, usage, transcripts and
audit events. Calls are synchronous and must run off the event loop, matching
the existing Redis/S3/Milvus boundary.
"""
from __future__ import annotations

import logging
import json
from contextlib import contextmanager
from threading import Lock
from time import perf_counter
from typing import Iterator, Optional

from sqlalchemy import create_engine, pool, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.core.config import AppConfig, get_config
from app.db_contract import AUTH_LOOKUP_FUNCTION, TABLE_COLUMNS, TABLE_PRIVILEGES

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
                hide_parameters=True,
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


def dispose_engines(*, close: bool = True) -> None:
    """Release pooled connections on shutdown or after config changes."""
    global _engine, _engine_key, _session_factory
    with _lock:
        if _engine is not None:
            _engine.dispose(close=close)
        _engine = None
        _engine_key = None
        _session_factory = None


def _ping_database(config: AppConfig) -> None:
    # Do not wait behind the application's connection pool or run a 15s business
    # query. These connections cannot change the cached runtime engine settings.
    engine = create_engine(
        normalize_database_url(config.database_url or ""), poolclass=pool.NullPool,
        hide_parameters=True, connect_args={
            **_connect_args(config), "connect_timeout": 2,
            "options": "-c statement_timeout=2000 -c lock_timeout=1000",
        },
    )
    try:
        with engine.connect() as connection:
            stamp = connection.execute(text(f"SELECT version_num FROM {SCHEMA}.alembic_version")).scalars().all()
            if not stamp or not all(stamp):
                raise RuntimeError("Missing migration stamp")
            contract = [{"name": name, "columns": columns.split(), "privileges": TABLE_PRIVILEGES[name]}
                        for name, columns in TABLE_COLUMNS.items()]
            ready = connection.execute(text("""
                WITH required AS (
                    SELECT * FROM jsonb_to_recordset(CAST(:contract AS jsonb))
                        AS r(name text, columns text[], privileges text[])
                )
                SELECT bool_and(
                    to_regclass('doctrace.' || r.name) IS NOT NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM unnest(r.columns) AS wanted(name)
                        WHERE NOT EXISTS (
                            SELECT 1 FROM information_schema.columns c
                            WHERE c.table_schema = 'doctrace' AND c.table_name = r.name
                                AND c.column_name = wanted.name
                        )
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM unnest(r.privileges) AS required_privilege(name)
                        WHERE NOT COALESCE(has_table_privilege(
                            to_regclass('doctrace.' || r.name), required_privilege.name
                        ), false)
                    )
                )
                AND NOT EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = current_user
                    AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
                )
                AND NOT EXISTS (
                    SELECT 1 FROM pg_namespace WHERE nspname NOT LIKE 'pg_%'
                    AND nspname <> 'information_schema' AND has_schema_privilege(oid, 'CREATE')
                )
                AND NOT EXISTS (
                    SELECT 1 FROM pg_auth_members WHERE member = current_user::regrole
                )
                FROM required r
            """), {"contract": json.dumps(contract)}).scalar_one()
            if not ready:
                raise RuntimeError("Incomplete schema or runtime privileges")
            auth_ready = connection.execute(text("""
                SELECT p.prosecdef AND p.prokind = 'f' AND NOT p.proretset
                    AND p.prorettype = 'boolean'::regtype AND p.provolatile = 's'
                    AND p.proowner <> current_user::regrole::oid
                    AND ARRAY['search_path=""', 'row_security=off'] <@ p.proconfig
                    AND has_function_privilege(p.oid, 'EXECUTE')
                    AND NOT has_function_privilege(p.oid, 'EXECUTE WITH GRANT OPTION')
                    AND NOT EXISTS (
                        SELECT 1 FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) a
                        WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE'
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM pg_roles r
                        WHERE r.rolname IN ('anon', 'authenticated', 'service_role')
                            AND has_function_privilege(r.oid, p.oid, 'EXECUTE')
                    )
                    AND NOT has_schema_privilege(n.oid, 'USAGE')
                    AND NOT has_table_privilege(c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                    AND NOT has_any_column_privilege(c.oid, 'SELECT,INSERT,UPDATE,REFERENCES')
                FROM pg_proc p
                JOIN pg_namespace n ON n.nspname = 'auth'
                JOIN pg_class c ON c.relnamespace = n.oid AND c.relname = 'users'
                WHERE p.oid = to_regprocedure(:function)
            """), {"function": AUTH_LOOKUP_FUNCTION}).scalar_one_or_none()
            if not auth_ready:
                raise RuntimeError("Incomplete or excessive Auth lookup privileges")
            # Exercise underlying Auth access as the definer, even on an empty
            # database. No Auth identifiers or row contents leave this probe.
            connection.execute(text(
                "SELECT doctrace.auth_user_exists('00000000-0000-0000-0000-000000000000'::uuid)"
            )).scalar_one()
    finally:
        engine.dispose()


async def check_database(config: Optional[AppConfig] = None) -> dict:
    """Short dependency probe for /ready; never raises."""
    config = config or get_config()
    if not config.database_url:
        return {"status": "error", "latency_ms": None, "error_code": "database_not_configured"}
    started = perf_counter()
    try:
        await run_in_threadpool(_ping_database, config)
    except Exception:
        logger.warning("database_probe_failed", exc_info=True)
        return {
            "status": "error",
            "latency_ms": round((perf_counter() - started) * 1000),
            "error_code": "database_unavailable",
        }
    return {"status": "ok", "latency_ms": round((perf_counter() - started) * 1000)}
