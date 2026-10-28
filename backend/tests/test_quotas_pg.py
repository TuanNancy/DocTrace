"""Monthly quota admission against real Postgres; skipped without Docker.

Concurrent admissions must never overshoot the plan limit, duplicate request
ids must not reserve twice, and a rejected request must roll back cleanly.
"""
import asyncio
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, text

from app import db
from app.core.config import AppConfig
from app.services.quotas import QuotaService

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
    not _docker_available(), reason="Quota integration tests require a running Docker daemon",
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
def service(postgres_url, repository):
    db.dispose_engines()
    yield QuotaService(AppConfig(database_url=postgres_url), repository=repository)
    db.dispose_engines()


def execute(postgres_url, statement, params=None):
    engine = create_engine(postgres_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(statement), params or {})
    finally:
        engine.dispose()


def scalar(postgres_url, statement, params=None):
    engine = create_engine(postgres_url)
    try:
        with engine.connect() as connection:
            return connection.execute(text(statement), params or {}).scalar()
    finally:
        engine.dispose()


def create_workspace(postgres_url, plan="free"):
    workspace_id = str(uuid4())
    execute(
        postgres_url,
        "insert into doctrace.workspaces (id, name, kind, plan, created_by) "
        "values (:id, 'Nhóm', 'team', :plan, :id)",
        {"id": workspace_id, "plan": plan},
    )
    return workspace_id


def chat_count(postgres_url, workspace_id):
    return scalar(
        postgres_url,
        "select count(*) from doctrace.chat_requests where workspace_id = :workspace",
        {"workspace": workspace_id},
    )


def used_counter(postgres_url, workspace_id):
    return scalar(
        postgres_url,
        "select used from doctrace.usage_counters "
        "where workspace_id = :workspace and metric = 'chat_questions_month' "
        "and period_start = date_trunc('month', now() at time zone 'utc')::date",
        {"workspace": workspace_id},
    )


async def admit(service, workspace_id, user_id=None, plan="free", request_id=None):
    return await service.admit_chat(
        workspace_id, user_id or str(uuid4()), request_id or str(uuid4()),
        str(uuid4()), plan,
    )


async def test_free_chat_quota_rejects_exactly_at_the_limit(service, postgres_url):
    workspace_id = create_workspace(postgres_url)
    user_id = str(uuid4())

    admissions = [await admit(service, workspace_id, user_id) for _ in range(10)]
    assert [item["used"] for item in admissions] == list(range(1, 11))
    assert used_counter(postgres_url, workspace_id) == 10
    assert chat_count(postgres_url, workspace_id) == 10

    rejected_request = str(uuid4())
    with pytest.raises(HTTPException) as caught:
        await service.admit_chat(
            workspace_id, user_id, rejected_request, str(uuid4()), "free",
        )

    error = caught.value
    assert error.status_code == 429
    assert error.detail["code"] == "quota_exceeded"
    assert error.detail["metric"] == "chat_questions_month"
    assert error.detail["limit"] == 10
    assert error.detail["used"] == 10
    assert error.detail["reset_at"].endswith("Z")
    assert int(error.headers["Retry-After"]) == error.detail["retry_after"]
    # The rejected INSERT rolled back with the quota transaction.
    assert chat_count(postgres_url, workspace_id) == 10
    assert await service.existing_chat(workspace_id, user_id, rejected_request) is None

    # Upgrading the workspace lets the same client request id succeed.
    execute(
        postgres_url,
        "update doctrace.workspaces set plan = 'pro' where id = :workspace",
        {"workspace": workspace_id},
    )
    granted = await service.admit_chat(
        workspace_id, user_id, rejected_request, str(uuid4()), "pro",
    )
    assert granted["used"] == 11
    assert granted["limit"] == 100
    assert chat_count(postgres_url, workspace_id) == 11

    # A downgrade keeps the used count and blocks new questions immediately.
    execute(postgres_url, "update doctrace.workspaces set plan = 'free' where id = :workspace",
            {"workspace": workspace_id})
    with pytest.raises(HTTPException) as downgraded:
        await service.admit_chat(
            workspace_id, user_id, str(uuid4()), str(uuid4()), "free",
        )
    assert downgraded.value.detail["used"] == 11
    assert downgraded.value.detail["limit"] == 10
    assert chat_count(postgres_url, workspace_id) == 11


async def test_new_month_starts_a_fresh_counter(service, postgres_url):
    workspace_id = create_workspace(postgres_url)
    user_id = str(uuid4())
    execute(
        postgres_url,
        "insert into doctrace.usage_counters (workspace_id, period_start, metric, used) "
        "values (:workspace, "
        "(date_trunc('month', now() at time zone 'utc') - interval '1 month')::date, "
        "'chat_questions_month', 10)",
        {"workspace": workspace_id},
    )

    admission = await admit(service, workspace_id, user_id)

    assert admission["used"] == 1
    assert used_counter(postgres_url, workspace_id) == 1


async def test_concurrent_chats_never_overshoot_the_monthly_limit(service, postgres_url):
    workspace_id = create_workspace(postgres_url)
    user_id = str(uuid4())

    results = await asyncio.gather(*[
        admit(service, workspace_id, user_id, plan="free") for _ in range(14)
    ], return_exceptions=True)

    admitted = [result for result in results if isinstance(result, dict)]
    rejected = [
        result for result in results
        if isinstance(result, HTTPException) and result.status_code == 429
    ]
    assert len(admitted) == 10
    assert len(rejected) == 4
    assert all(error.detail["code"] == "quota_exceeded" for error in rejected)
    assert used_counter(postgres_url, workspace_id) == 10
    assert chat_count(postgres_url, workspace_id) == 10
    assert max(item["used"] for item in admitted) == 10


async def test_concurrent_pro_chats_admit_exactly_the_plan_limit(service, postgres_url):
    """Pro allows 100 questions; 102 concurrent admissions must not overshoot."""
    workspace_id = create_workspace(postgres_url, plan="pro")
    user_id = str(uuid4())

    results = await asyncio.gather(*[
        admit(service, workspace_id, user_id, plan="pro") for _ in range(102)
    ], return_exceptions=True)

    assert sum(isinstance(result, dict) for result in results) == 100
    assert sum(
        isinstance(result, HTTPException) and result.status_code == 429
        for result in results
    ) == 2
    assert used_counter(postgres_url, workspace_id) == 100
    assert chat_count(postgres_url, workspace_id) == 100


async def test_duplicate_chat_request_reserves_one_question(service, postgres_url):
    workspace_id = create_workspace(postgres_url)
    user_id = str(uuid4())
    request_id = str(uuid4())

    first = await service.admit_chat(
        workspace_id, user_id, request_id, str(uuid4()), "free",
    )
    with pytest.raises(HTTPException) as caught:
        await service.admit_chat(
            workspace_id, user_id, request_id, str(uuid4()), "free",
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "request_in_progress"
    assert caught.value.detail["chat_request_id"] == first["chat_request_id"]
    assert used_counter(postgres_url, workspace_id) == 1
    assert chat_count(postgres_url, workspace_id) == 1


async def test_concurrent_duplicates_cannot_both_reserve(service, postgres_url):
    workspace_id = create_workspace(postgres_url)
    user_id = str(uuid4())
    request_id = str(uuid4())

    results = await asyncio.gather(
        service.admit_chat(workspace_id, user_id, request_id, str(uuid4()), "free"),
        service.admit_chat(workspace_id, user_id, request_id, str(uuid4()), "free"),
        return_exceptions=True,
    )

    assert sum(isinstance(result, dict) for result in results) == 1
    duplicate = next(result for result in results if isinstance(result, HTTPException))
    assert duplicate.status_code == 409
    assert duplicate.detail["code"] == "request_in_progress"
    assert used_counter(postgres_url, workspace_id) == 1
    assert chat_count(postgres_url, workspace_id) == 1


async def test_terminal_chat_status_supports_completed_idempotency(service, postgres_url):
    workspace_id = create_workspace(postgres_url)
    user_id = str(uuid4())
    request_id = str(uuid4())
    admission = await service.admit_chat(
        workspace_id, user_id, request_id, str(uuid4()), "free",
    )
    chat_request_id = admission["chat_request_id"]

    assert await service.mark_chat_status(chat_request_id, "streaming") is True
    assert await service.mark_chat_status(chat_request_id, "completed") is True
    assert await service.mark_chat_status(chat_request_id, "completed") is False

    existing = await service.existing_chat(workspace_id, user_id, request_id)
    assert existing["status"] == "completed"

    with pytest.raises(HTTPException) as caught:
        await service.admit_chat(
            workspace_id, user_id, request_id, str(uuid4()), "free",
        )
    assert caught.value.detail["code"] == "request_completed"


async def test_usage_is_owner_scoped_and_unknown_costs_stay_visible(service, postgres_url):
    workspace_id = create_workspace(postgres_url, plan="pro")
    owner = str(uuid4())
    member = str(uuid4())
    doc_id = str(uuid4())
    execute(
        postgres_url,
        "insert into doctrace.usage_counters "
        "(workspace_id, period_start, metric, used) "
        "values (:workspace, date_trunc('month', now() at time zone 'utc')::date, "
        "'chat_questions_month', 3)",
        {"workspace": workspace_id},
    )
    for user_id, status in ((owner, "completed"), (owner, "failed"), (member, "completed")):
        execute(
            postgres_url,
            "insert into doctrace.chat_requests "
            "(request_id, workspace_id, user_id, doc_id, status) "
            "values (:request, :workspace, :user, :doc, :status)",
            {
                "request": str(uuid4()), "workspace": workspace_id,
                "user": user_id, "doc": doc_id, "status": status,
            },
        )
    for user_id, cost, cost_status in (
        (owner, 1_000_000, "reported"),
        (owner, None, "unknown"),
        (member, 2_000_000, "reported"),
        (None, 500_000, "reported"),
        (None, None, "unknown"),
    ):
        execute(
            postgres_url,
            "insert into doctrace.provider_calls "
            "(workspace_id, user_id, kind, model, cost_micros, cost_status) "
            "values (:workspace, :user, 'answer', 'test-model', :cost, :cost_status)",
            {
                "workspace": workspace_id, "user": user_id,
                "cost": cost, "cost_status": cost_status,
            },
        )

    # Neighboring UTC months must not enter the current month's aggregates.
    for offset in (-1, 1):
        params = {"w": workspace_id, "u": member, "d": doc_id, "r": str(uuid4()), "offset": offset}
        execute(postgres_url,
                "insert into doctrace.chat_requests (request_id, workspace_id, user_id, doc_id, status, created_at) "
                "values (:r, :w, :u, :d, 'completed', (date_trunc('month', now() at time zone 'utc') "
                "+ make_interval(months => :offset)) at time zone 'utc')", params)
        execute(postgres_url,
                "insert into doctrace.provider_calls (workspace_id, user_id, kind, model, cost_micros, cost_status, created_at) "
                "values (:w, :u, 'answer', 'outside-period', 999999999, 'reported', "
                "(date_trunc('month', now() at time zone 'utc') + make_interval(months => :offset)) at time zone 'utc')", params)

    owner_usage = await service.usage(workspace_id, "pro", owner, "owner")
    assert owner_usage["scope"] == "workspace"
    assert owner_usage["costs"] == {"known_micros": 3_500_000, "unknown_calls": 2}
    assert owner_usage["chat"] == {
        "used": 3, "limit": 100, "remaining": 97, "metric": "chat_questions_month",
    }
    assert owner_usage["documents"] == {
        "used": 0, "limit": 50, "remaining": 50, "metric": "documents",
    }
    assert {row["user_id"]: row for row in owner_usage["by_user"]} == {
        owner: {
            "user_id": owner, "chat_questions": 2,
            "cost_micros": 1_000_000, "cost_unknown_calls": 1,
        },
        member: {
            "user_id": member, "chat_questions": 1,
            "cost_micros": 2_000_000, "cost_unknown_calls": 0,
        },
    }

    member_usage = await service.usage(workspace_id, "pro", member, "member")
    assert member_usage["scope"] == "self"
    assert member_usage["chat"] == {
        "used": 1, "limit": 100, "remaining": None, "metric": "chat_questions_month",
    }
    assert member_usage["documents"]["remaining"] is None
    assert member_usage["costs"] == {"known_micros": 2_000_000, "unknown_calls": 0}
    assert member_usage["by_user"] == [{
        "user_id": member, "chat_questions": 1,
        "cost_micros": 2_000_000, "cost_unknown_calls": 0,
    }]

    assert await service.document_limit("free") == 5
    assert await service.document_limit("pro") == 50


async def test_usage_with_only_unknown_costs_does_not_claim_a_free_call(service, postgres_url):
    workspace_id, user_id = create_workspace(postgres_url), str(uuid4())
    execute(postgres_url,
            "insert into doctrace.provider_calls (workspace_id, user_id, kind, model, cost_status) "
            "values (:w, :u, 'index_embedding', 'test-model', 'unknown')",
            {"w": workspace_id, "u": user_id})
    result = await service.usage(workspace_id, "free", user_id, "member")
    assert result["costs"] == {"known_micros": 0, "unknown_calls": 1}
    assert result["by_user"] == [{
        "user_id": user_id, "chat_questions": 0, "cost_micros": 0, "cost_unknown_calls": 1,
    }]
    empty = await service.usage(workspace_id, "free", str(uuid4()), "member")
    assert empty["chat"]["used"] == 0
    assert empty["chat"]["remaining"] is None
    assert empty["costs"] == {"known_micros": 0, "unknown_calls": 0}
    assert empty["by_user"] == []
