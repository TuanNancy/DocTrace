"""Real Postgres migration coverage; skips when Docker is unavailable locally."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

BACKEND = Path(__file__).resolve().parents[1]
CONTROL_TABLES = {
    "workspaces", "workspace_members", "platform_admins", "profiles", "plan_limits",
    "audit_events", "conversations", "messages", "chat_requests", "provider_calls",
    "usage_counters",
}


def _docker_available() -> bool:
    try:
        import docker

        client = docker.from_env(timeout=2)
        try:
            return client.ping()
        finally:
            client.close()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _docker_available(), reason="Postgres migration tests require a running Docker daemon",
)


@pytest.fixture(scope="module")
def postgres_url():
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer("postgres:16-alpine", driver="psycopg")
    container.start()
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture()
def clean_database(postgres_url):
    engine = create_engine(postgres_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS doctrace CASCADE"))
    engine.dispose()
    return postgres_url


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_fresh_upgrade_seeds_plans_and_is_idempotent(clean_database):
    config = alembic_config(clean_database)
    command.upgrade(config, "head")
    command.upgrade(config, "head")

    engine = create_engine(clean_database)
    try:
        tables = set(inspect(engine).get_table_names(schema="doctrace"))
        assert CONTROL_TABLES <= tables
        with engine.connect() as connection:
            rows = connection.execute(text(
                "select plan, metric, limit_value from doctrace.plan_limits "
                "order by plan, metric"
            )).all()
            assert [tuple(row) for row in rows] == [
                ("free", "chat_questions_month", 10),
                ("free", "documents", 5),
                ("free", "workspaces", 1),
                ("pro", "chat_questions_month", 100),
                ("pro", "documents", 50),
                ("pro", "workspaces", 10),
            ]
            assert connection.execute(text(
                "select to_regclass('doctrace.alembic_version') is not null"
            )).scalar() is True
    finally:
        engine.dispose()


def test_downgrade_removes_control_plane_tables(clean_database):
    config = alembic_config(clean_database)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(clean_database)
    try:
        tables = set(inspect(engine).get_table_names(schema="doctrace"))
        assert not (CONTROL_TABLES & tables)
    finally:
        engine.dispose()
