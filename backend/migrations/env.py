"""Alembic environment for the doctrace control-plane schema.

Migrations use a direct/session-pooler URL with DDL rights, never the runtime
pooler. A transaction-scoped advisory lock serializes concurrent deploys.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db import SCHEMA, normalize_database_url  # noqa: E402
from migrations.permissions import grant_runtime_access  # noqa: E402

config = context.config
logger = logging.getLogger("alembic.env")


def database_url() -> str:
    configured = (config.get_main_option("sqlalchemy.url") or "").strip()
    url = configured or os.environ.get("DIRECT_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DIRECT_DATABASE_URL is required to run migrations; runtime DATABASE_URL is never used."
        )
    return normalize_database_url(url)


def connect_args() -> dict:
    return {
        "connect_timeout": 10,
        "application_name": "doctrace-migrate",
        "prepare_threshold": None,
    }


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=SCHEMA,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(
        database_url(), poolclass=pool.NullPool, connect_args=connect_args(), hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
            connection.commit()
            context.configure(
                connection=connection,
                target_metadata=None,
                version_table_schema=SCHEMA,
                include_schemas=True,
                compare_type=True,
            )
            with context.begin_transaction():
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext('doctrace:migrations'))")
                )
                context.run_migrations()
                # Downgrade is for isolated testing only; it may remove tables.
                if context.get_context().get_current_revision() is not None:
                    grant_runtime_access(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
