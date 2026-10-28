"""Real Postgres migration coverage; skips when Docker is unavailable locally."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from uuid import uuid4

from app import db
from app.core.config import AppConfig
from app.services.quotas import QuotaService
from app.services.transcripts import TranscriptService
from app.services.workspaces import WorkspaceService

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


@pytest.fixture
def runtime_database(clean_database):
    engine = create_engine(clean_database)
    script = (BACKEND.parent / "deploy/postgres/bootstrap-runtime-role.sql").read_text()
    with engine.begin() as connection:
        connection.exec_driver_sql(script)
        connection.exec_driver_sql(script)
        connection.exec_driver_sql("ALTER ROLE doctrace_app PASSWORD 'local-test-only'")
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS auth")
        connection.exec_driver_sql("CREATE TABLE IF NOT EXISTS auth.users (id uuid)")
    command.upgrade(alembic_config(clean_database), "head")
    command.upgrade(alembic_config(clean_database), "head")
    runtime_url = make_url(clean_database).set(username="doctrace_app", password="local-test-only")
    config = AppConfig(database_url=runtime_url.render_as_string(hide_password=False))
    try:
        yield engine, config
    finally:
        db.dispose_engines()
        engine.dispose()


async def test_unprivileged_runtime_supports_workspace_quota_transcript_flow(runtime_database, repository):
    _, config = runtime_database
    assert (await db.check_database(config))["status"] == "ok"
    user_id, doc_id = str(uuid4()), str(uuid4())
    workspaces = await WorkspaceService(config).list_for_user(user_id)
    assert workspaces[0]["id"] == user_id
    quotas = QuotaService(config, repository=repository)
    admitted = await quotas.admit_chat(user_id, user_id, str(uuid4()), doc_id, "free", query="private-content")
    assert admitted["used"] == 1
    transcripts = TranscriptService(config)
    await transcripts.mark_streaming(admitted["assistant_message_id"])
    await transcripts.finalize_message(admitted["assistant_message_id"], "complete", "private-answer", [])
    await quotas.mark_chat_status(admitted["chat_request_id"], "completed")
    assert (await quotas.usage(user_id, "free", user_id, "owner"))["chat"]["used"] == 1
    assert await transcripts.delete(user_id, user_id, admitted["conversation_id"])


@pytest.mark.parametrize("statement", [
    "CREATE TABLE doctrace.forbidden (id int)",
    "CREATE SCHEMA forbidden",
    "ALTER TABLE doctrace.messages ADD COLUMN forbidden text",
    "DROP TABLE doctrace.messages",
    "UPDATE doctrace.plan_limits SET limit_value = 999",
    "INSERT INTO doctrace.platform_admins (user_id) VALUES (gen_random_uuid())",
    "UPDATE doctrace.audit_events SET action = 'forged'",
    "DELETE FROM doctrace.audit_events",
    "UPDATE doctrace.alembic_version SET version_num = 'forged'",
    "SELECT * FROM auth.users",
])
def test_runtime_cannot_ddl_escalate_rewrite_audit_or_read_auth(runtime_database, statement):
    _, config = runtime_database
    with pytest.raises(DBAPIError) as error:
        with db.get_engine(config).begin() as connection:
            connection.execute(text(statement))
    assert error.value.orig.sqlstate == "42501"


@pytest.mark.parametrize("damage", [
    "DROP TABLE doctrace.provider_calls",
    "ALTER TABLE doctrace.messages DROP COLUMN sources",
    "DELETE FROM doctrace.alembic_version",
    "REVOKE INSERT ON doctrace.messages FROM doctrace_app",
    "REVOKE USAGE ON SCHEMA doctrace FROM doctrace_app",
])
async def test_readiness_rejects_partial_schema_or_missing_runtime_grants(runtime_database, damage):
    admin, config = runtime_database
    assert (await db.check_database(config))["status"] == "ok"
    with admin.begin() as connection:
        connection.exec_driver_sql(damage)
    assert (await db.check_database(config))["status"] == "error"


async def test_readiness_allows_additive_migrations_but_rejects_admin_identity(runtime_database):
    admin, config = runtime_database
    with admin.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE doctrace.messages ADD COLUMN future_metadata text")
        connection.exec_driver_sql("UPDATE doctrace.alembic_version SET version_num = 'future_expand_revision'")
    assert (await db.check_database(config))["status"] == "ok"
    privileged = AppConfig(database_url=admin.url.render_as_string(hide_password=False))
    assert (await db.check_database(privileged))["status"] == "error"
