"""Provider-call persistence and generation upsert against real Postgres.

Skipped locally when Docker is unavailable; CI runs it with testcontainers.
"""
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text

from app import db
from app.core.config import AppConfig
from app.services.provider_calls import UsageAttribution, UsageCollector

BACKEND = Path(__file__).resolve().parents[1]


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
    not _docker_available(), reason="Provider-call integration tests require Docker",
)


@pytest.fixture(scope="module")
def postgres_url(install_auth_schema):
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer("postgres:16-alpine", driver="psycopg")
    container.start()
    try:
        url = container.get_connection_url()
        migration_url = install_auth_schema(url)
        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", migration_url)
        command.upgrade(config, "head")
        yield url
    finally:
        container.stop()


@pytest.fixture
def config(postgres_url):
    db.dispose_engines()
    yield AppConfig(database_url=postgres_url, openrouter_api_key=None)
    db.dispose_engines()


def execute(postgres_url, statement, params=None):
    engine = create_engine(postgres_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(statement), params or {})
    finally:
        engine.dispose()


def create_personal_workspace(postgres_url, workspace_id):
    execute(
        postgres_url,
        "insert into doctrace.workspaces "
        "(id, name, kind, plan, created_by, personal_owner_user_id) "
        "values (:id, 'Cá nhân', 'personal', 'free', :id, :id)",
        {"id": workspace_id},
    )


def rows(postgres_url, workspace=None):
    engine = create_engine(postgres_url)
    try:
        statement = (
            "select kind, generation_id, prompt_tokens, cost_micros, cost_status, "
            "workspace_id, user_id, doc_id, request_id, job_id "
            "from doctrace.provider_calls"
        )
        params = {}
        if workspace is not None:
            statement += " where workspace_id = :workspace"
            params["workspace"] = workspace
        statement += " order by kind"
        with engine.connect() as connection:
            return connection.execute(text(statement), params).mappings().all()
    finally:
        engine.dispose()


async def test_collector_persists_unknown_cost_and_upserts_generation(config, postgres_url):
    workspace = str(uuid4())
    user = str(uuid4())
    doc = str(uuid4())
    first_request = str(uuid4())
    create_personal_workspace(postgres_url, workspace)

    first = UsageCollector(
        UsageAttribution(
            workspace_id=workspace, user_id=user, doc_id=doc,
            request_id=first_request, job_id="job-1",
        ),
        config=config,
    )
    answer = first.start("answer", "chat-model")
    answer.apply_usage({
        "prompt_tokens": 10, "completion_tokens": 2, "cost": "0.000123",
    })
    answer.generation_id = "gen-upsert"
    await first.flush()

    # A retry/reconciliation must update the same row, not insert a second one.
    second = UsageCollector(
        UsageAttribution(
            workspace_id=workspace, user_id=user, doc_id=doc,
            request_id=str(uuid4()), job_id="job-2",
        ),
        config=config,
    )
    retried = second.start("answer", "chat-model")
    retried.apply_usage({
        "prompt_tokens": 12, "completion_tokens": 3, "cost": "0.000150",
    })
    retried.generation_id = "gen-upsert"
    summary = second.start("summary", "chat-model")
    summary.apply_usage({"prompt_tokens": 4, "completion_tokens": 1})
    await second.flush()

    recorded = rows(postgres_url, workspace)
    assert len(recorded) == 2
    answer_row = next(row for row in recorded if row["kind"] == "answer")
    assert answer_row["prompt_tokens"] == 12
    assert answer_row["cost_micros"] == 150
    assert answer_row["cost_status"] == "reported"
    assert str(answer_row["workspace_id"]) == workspace
    assert str(answer_row["user_id"]) == user
    assert str(answer_row["doc_id"]) == doc
    assert str(answer_row["request_id"]) == first_request
    assert answer_row["job_id"] == "job-1"

    summary_row = next(row for row in recorded if row["kind"] == "summary")
    assert summary_row["generation_id"] is None
    assert summary_row["cost_micros"] is None
    assert summary_row["cost_status"] == "unknown"


async def test_malformed_attribution_is_null_not_a_failed_insert(config, postgres_url):
    workspace = str(uuid4())
    create_personal_workspace(postgres_url, workspace)
    collector = UsageCollector(
        UsageAttribution(
            workspace_id=workspace, user_id="not-a-uuid", doc_id="doc",
            request_id="request", job_id="job-1",
        ),
        config=config,
    )
    collector.start("answer", "chat-model").apply_usage({"prompt_tokens": 1})
    await collector.flush()

    row = rows(postgres_url, workspace)[0]
    assert str(row["workspace_id"]) == workspace
    assert row["user_id"] is None
    assert row["doc_id"] is None
    assert row["request_id"] is None
    assert row["cost_micros"] is None
