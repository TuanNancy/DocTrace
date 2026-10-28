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
    "usage_counters", "document_failures", "workspace_purges", "workspace_purge_documents",
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
def clean_database(postgres_url, install_auth_schema):
    engine = create_engine(postgres_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS doctrace CASCADE"))
        connection.execute(text("DROP SCHEMA IF EXISTS auth CASCADE"))
    engine.dispose()
    return install_auth_schema(postgres_url)


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


def test_migration_identity_has_hosted_auth_permissions_without_schema_grant_option(clean_database):
    engine = create_engine(clean_database)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("""
                SELECT NOT rolsuper AND rolbypassrls
                    AND has_schema_privilege('auth', 'USAGE')
                    AND NOT has_schema_privilege('auth', 'USAGE WITH GRANT OPTION')
                    AND has_column_privilege('auth.users', 'id', 'SELECT')
                    AND has_column_privilege('auth.users', 'deleted_at', 'SELECT')
                    AND NOT pg_has_role(current_user, 'supabase_admin', 'MEMBER')
                    AND NOT pg_has_role(current_user, 'supabase_auth_admin', 'MEMBER')
                FROM pg_roles WHERE rolname = current_user
            """)).scalar_one() is True
    finally:
        engine.dispose()


def test_upgrade_from_existing_control_plane_preserves_data(clean_database):
    config = alembic_config(clean_database)
    command.upgrade(config, "0001_control_plane")
    engine = create_engine(clean_database)
    workspace = str(uuid4())
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO doctrace.workspaces (id, name, kind, created_by) "
                "VALUES (:id, 'Existing team', 'team', :id)"
            ), {"id": workspace})
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT name FROM doctrace.workspaces WHERE id = :id"),
                                      {"id": workspace}).scalar_one() == "Existing team"
            assert connection.execute(text("SELECT version_num FROM doctrace.alembic_version")).scalar_one() == "0004_answer_cache"
            assert connection.execute(text("SELECT count(*) FROM pg_policy WHERE polrelid = 'auth.users'::regclass")).scalar_one() == 0
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
def runtime_database(clean_database, postgres_url):
    engine = create_engine(postgres_url)
    script = (BACKEND.parent / "deploy/postgres/bootstrap-runtime-role.sql").read_text()
    with engine.begin() as connection:
        connection.exec_driver_sql(script)
        connection.exec_driver_sql(script)
        connection.exec_driver_sql("ALTER ROLE doctrace_app PASSWORD 'local-test-only'")
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


def test_private_auth_lookup_returns_only_active_existence_and_repairs_grants(runtime_database, clean_database):
    admin, config = runtime_database
    active, deleted = str(uuid4()), str(uuid4())
    with admin.begin() as connection:
        connection.execute(text(
            "INSERT INTO auth.users (id, email, encrypted_password) VALUES (:id, 'private@example.test', 'secret')"
        ), {"id": active})
        connection.execute(text("INSERT INTO auth.users (id, deleted_at) VALUES (:id, now())"), {"id": deleted})
    with db.get_engine(config).connect() as connection:
        assert connection.execute(text("SELECT has_schema_privilege('auth', 'USAGE')")).scalar_one() is False
        for user_id, expected in ((active, True), (deleted, False), (str(uuid4()), False)):
            assert connection.execute(text("SELECT doctrace.auth_user_exists(CAST(:id AS uuid))"),
                                      {"id": user_id}).scalar_one() is expected
        # Caller-controlled search paths/temp tables cannot change the lookup.
        connection.exec_driver_sql("CREATE TEMP TABLE users (id uuid, deleted_at timestamptz)")
        connection.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": deleted})
        connection.exec_driver_sql("SET LOCAL search_path = pg_temp, public")
        assert connection.execute(text("SELECT doctrace.auth_user_exists(CAST(:id AS uuid))"),
                                  {"id": deleted}).scalar_one() is False
    # No-op upgrades repair missing/overbroad EXECUTE grants without changing
    # Auth rows, policies or schema privileges.
    with admin.begin() as connection:
        connection.exec_driver_sql("REVOKE EXECUTE ON FUNCTION doctrace.auth_user_exists(uuid) FROM doctrace_app")
        connection.exec_driver_sql("GRANT EXECUTE ON FUNCTION doctrace.auth_user_exists(uuid) TO PUBLIC, anon, authenticated, service_role")
    command.upgrade(alembic_config(clean_database), "head")
    with db.get_engine(config).connect() as connection:
        assert connection.execute(text("SELECT doctrace.auth_user_exists(CAST(:id AS uuid))"),
                                  {"id": active}).scalar_one() is True
        assert connection.execute(text("SELECT has_function_privilege('anon', 'doctrace.auth_user_exists(uuid)', 'EXECUTE')")).scalar_one() is False
    with admin.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM auth.users")).scalar_one() == 2
        assert connection.execute(text("SELECT count(*) FROM pg_policy WHERE polrelid = 'auth.users'::regclass")).scalar_one() == 0
        assert connection.execute(text("SELECT proowner::regrole::text FROM pg_proc WHERE oid = 'doctrace.auth_user_exists(uuid)'::regprocedure")).scalar_one() == "doctrace_migrator"


@pytest.mark.parametrize("role", ["anon", "authenticated", "service_role"])
@pytest.mark.parametrize("statement", [
    "SELECT doctrace.auth_user_exists(gen_random_uuid())",
    "SELECT * FROM doctrace.workspace_members",
])
def test_auth_lookup_does_not_grant_data_api_roles_access(runtime_database, role, statement):
    admin, _ = runtime_database
    with admin.begin() as connection:
        assert connection.execute(text("SELECT has_schema_privilege(:role, 'doctrace', 'USAGE')"),
                                  {"role": role}).scalar_one() is False
        # Even accidental schema exposure must not expose our privileged helper.
        connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA doctrace TO "{role}"')
        connection.exec_driver_sql(f'SET LOCAL ROLE "{role}"')
        with pytest.raises(DBAPIError) as error:
            connection.exec_driver_sql(statement)
        assert error.value.orig.sqlstate == "42501"


@pytest.mark.parametrize("statement", [
    "CREATE TABLE doctrace.forbidden (id int)",
    "CREATE SCHEMA forbidden",
    "ALTER TABLE doctrace.messages ADD COLUMN forbidden text",
    "DROP TABLE doctrace.messages",
    "UPDATE doctrace.plan_limits SET limit_value = 999",
    "INSERT INTO doctrace.platform_admins (user_id) VALUES (gen_random_uuid())",
    "UPDATE doctrace.audit_events SET action = 'forged'",
    "DELETE FROM doctrace.audit_events",
    "UPDATE doctrace.document_failures SET error_code = 'index_failed'",
    "DELETE FROM doctrace.document_failures",
    "DELETE FROM doctrace.workspace_purges",
    "UPDATE doctrace.alembic_version SET version_num = 'forged'",
    "SELECT * FROM auth.users",
    "SELECT id, deleted_at FROM auth.users",
    "SELECT email FROM auth.users",
    "SELECT encrypted_password FROM auth.users",
    "SELECT raw_user_meta_data FROM auth.users",
    "INSERT INTO auth.users (id) VALUES (gen_random_uuid())",
    "UPDATE auth.users SET deleted_at = NULL",
    "DELETE FROM auth.users",
    "ALTER TABLE auth.users DISABLE ROW LEVEL SECURITY",
    "ALTER FUNCTION doctrace.auth_user_exists(uuid) SECURITY INVOKER",
    "CREATE OR REPLACE FUNCTION doctrace.auth_user_exists(p_user_id uuid) RETURNS boolean LANGUAGE sql AS 'SELECT true'",
])
def test_runtime_cannot_ddl_escalate_rewrite_audit_or_read_private_auth(runtime_database, statement):
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
    "REVOKE INSERT ON doctrace.workspace_purges FROM doctrace_app",
    "REVOKE UPDATE ON doctrace.workspace_purges FROM doctrace_app",
    "REVOKE INSERT ON doctrace.workspace_purge_documents FROM doctrace_app",
    "REVOKE UPDATE ON doctrace.workspace_purge_documents FROM doctrace_app",
    "REVOKE DELETE ON doctrace.workspace_purge_documents FROM doctrace_app",
    "REVOKE USAGE ON SCHEMA doctrace FROM doctrace_app",
    "DROP FUNCTION doctrace.auth_user_exists(uuid)",
    "REVOKE EXECUTE ON FUNCTION doctrace.auth_user_exists(uuid) FROM doctrace_app",
    "ALTER FUNCTION doctrace.auth_user_exists(uuid) SECURITY INVOKER",
    "ALTER FUNCTION doctrace.auth_user_exists(uuid) RESET search_path",
    "ALTER FUNCTION doctrace.auth_user_exists(uuid) RESET row_security",
    "ALTER FUNCTION doctrace.auth_user_exists(uuid) OWNER TO doctrace_app",
    "GRANT EXECUTE ON FUNCTION doctrace.auth_user_exists(uuid) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION doctrace.auth_user_exists(uuid) TO anon",
    "GRANT EXECUTE ON FUNCTION doctrace.auth_user_exists(uuid) TO authenticated",
    "GRANT EXECUTE ON FUNCTION doctrace.auth_user_exists(uuid) TO service_role",
    "GRANT EXECUTE ON FUNCTION doctrace.auth_user_exists(uuid) TO doctrace_app WITH GRANT OPTION",
    "REVOKE SELECT (id) ON auth.users FROM doctrace_migrator",
    "REVOKE SELECT (deleted_at) ON auth.users FROM doctrace_migrator",
    "REVOKE USAGE ON SCHEMA auth FROM doctrace_migrator",
    "ALTER ROLE doctrace_migrator NOBYPASSRLS",
    "GRANT USAGE ON SCHEMA auth TO doctrace_app",
    "GRANT SELECT ON auth.users TO doctrace_app",
    "GRANT SELECT (encrypted_password) ON auth.users TO doctrace_app",
    "GRANT UPDATE (id) ON auth.users TO doctrace_app",
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
