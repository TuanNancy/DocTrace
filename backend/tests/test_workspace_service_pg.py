"""Workspace control plane against a real Postgres; skips without Docker."""
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, text

from app import db
from app.core.config import AppConfig
from app.services.workspaces import WorkspaceService

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
    not _docker_available(), reason="Workspace integration tests require a running Docker daemon",
)


@pytest.fixture(scope="module")
def postgres_url():
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer("postgres:16-alpine", driver="psycopg")
    container.start()
    try:
        url = container.get_connection_url()
        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")
        yield url
    finally:
        container.stop()


@pytest.fixture
def service(postgres_url):
    db.dispose_engines()
    yield WorkspaceService(AppConfig(database_url=postgres_url))
    db.dispose_engines()


def execute(postgres_url, statement, params=None):
    engine = create_engine(postgres_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(statement), params or {})
    finally:
        engine.dispose()


async def provision_personal(service):
    user_id = str(uuid4())
    workspaces = await service.list_for_user(user_id)
    assert [workspace["id"] for workspace in workspaces] == [user_id]
    return user_id, workspaces[0]


async def test_personal_workspace_is_idempotent_and_membership_is_verified(service, postgres_url):
    user_id, workspace = await provision_personal(service)
    assert workspace == {**workspace, "kind": "personal", "role": "owner", "plan": "free",
                         "status": "active"}
    again = await service.list_for_user(user_id)
    assert len(again) == 1

    context = await service.resolve(user_id, user_id)
    assert (context.workspace_id, context.user_id, context.role) == (user_id, user_id, "owner")

    with pytest.raises(HTTPException) as error:
        await service.resolve(str(uuid4()), user_id)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        await service.resolve(user_id, str(uuid4()))
    assert error.value.status_code == 404


async def test_creation_respects_plan_limit_then_adds_the_owner(service, postgres_url):
    user_id, _ = await provision_personal(service)
    with pytest.raises(HTTPException) as error:
        await service.create(user_id, "Nhóm")
    assert error.value.status_code == 403
    assert error.value.detail["code"] == "plan_required"

    execute(postgres_url, "update doctrace.workspaces set plan = 'pro' where id = :id",
            {"id": user_id})
    workspace = await service.create(user_id, "  Nhóm  ")
    assert (workspace["name"], workspace["kind"], workspace["role"]) == ("Nhóm", "team", "owner")
    members = await service.members(user_id, workspace["id"])
    assert [(member["user_id"], member["role"]) for member in members] == [(user_id, "owner")]


async def test_member_removal_requires_cleanup_and_archive_is_owner_scoped(service, postgres_url):
    owner_id, _ = await provision_personal(service)
    execute(postgres_url, "update doctrace.workspaces set plan = 'pro' where id = :id",
            {"id": owner_id})
    workspace = await service.create(owner_id, "Nhóm")
    workspace_id = workspace["id"]
    member_id = str(uuid4())
    await service.add_member(owner_id, workspace_id, member_id)
    assert [member["user_id"] for member in await service.members(owner_id, workspace_id)] == [
        owner_id, member_id,
    ]

    with pytest.raises(HTTPException) as error:
        await service.assert_owner(member_id, workspace_id)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        await service.remove_member(owner_id, workspace_id, member_id, document_count=2)
    assert error.value.status_code == 409
    assert error.value.detail["document_count"] == 2
    with pytest.raises(HTTPException) as error:
        await service.remove_member(owner_id, workspace_id, owner_id, document_count=0)
    assert error.value.detail["code"] == "cannot_remove_owner"

    assert (await service.remove_member(owner_id, workspace_id, member_id, document_count=0))["status"] == "removed"
    assert [member["user_id"] for member in await service.members(owner_id, workspace_id)] == [owner_id]

    archived = await service.archive(owner_id, workspace_id)
    assert archived["status"] == "archived"
    with pytest.raises(HTTPException) as error:
        await service.resolve(owner_id, workspace_id)
    assert error.value.status_code == 404
    listed = await service.list_for_user(owner_id)
    assert {item["id"]: item["status"] for item in listed}[workspace_id] == "archived"

    with pytest.raises(HTTPException) as error:
        await service.restore(owner_id, workspace_id)
    assert error.value.status_code == 403

    admin_id = str(uuid4())
    execute(postgres_url,
            "insert into doctrace.platform_admins (user_id) values (:id)",
            {"id": admin_id})
    restored = await service.restore(admin_id, workspace_id)
    assert restored["status"] == "active"
    assert (await service.resolve(owner_id, workspace_id)).workspace_id == workspace_id
