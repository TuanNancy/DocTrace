"""Workspace control plane against a real Postgres; skips without Docker."""
import asyncio
from pathlib import Path
from threading import Event
from unittest.mock import Mock
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
import pytest
import fakeredis
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app import db
from app.core.config import AppConfig
from app.services.workspaces import WorkspaceService
from app.services.document_repository import DocumentRepository, workspace_user_key
from app.services import document_repository as catalog_module

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
def postgres_url(install_auth_schema):
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer("postgres:16-alpine", driver="psycopg")
    container.start()
    try:
        url = container.get_connection_url()
        migration_url = install_auth_schema(url)
        engine = create_engine(url)
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql((BACKEND.parent / "deploy/postgres/bootstrap-runtime-role.sql").read_text())
                connection.exec_driver_sql("ALTER ROLE doctrace_app PASSWORD 'local-test-only'")
        finally:
            engine.dispose()
        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", migration_url)
        command.upgrade(config, "head")
        yield url
    finally:
        container.stop()


@pytest.fixture
def service(postgres_url):
    db.dispose_engines()
    url = make_url(postgres_url).set(username="doctrace_app", password="local-test-only")
    yield WorkspaceService(AppConfig(database_url=url.render_as_string(hide_password=False)))
    db.dispose_engines()


@pytest.fixture
def catalog(service, monkeypatch):
    server = fakeredis.FakeServer()
    monkeypatch.setattr(catalog_module.Redis, "from_url", lambda *args, **kwargs: fakeredis.FakeRedis(server=server))
    return DocumentRepository(service.config), fakeredis.FakeRedis(server=server)


def execute(postgres_url, statement, params=None):
    engine = create_engine(postgres_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(statement), params or {})
    finally:
        engine.dispose()


def auth_user(postgres_url):
    user_id = str(uuid4())
    execute(postgres_url, "INSERT INTO auth.users (id) VALUES (:id)", {"id": user_id})
    return user_id


async def provision_personal(service, postgres_url):
    user_id = auth_user(postgres_url)
    workspaces = await service.list_for_user(user_id)
    assert [workspace["id"] for workspace in workspaces] == [user_id]
    return user_id, workspaces[0]


async def test_personal_workspace_is_idempotent_and_membership_is_verified(service, postgres_url):
    user_id, workspace = await provision_personal(service, postgres_url)
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
    user_id, _ = await provision_personal(service, postgres_url)
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


async def test_member_removal_requires_cleanup_and_archive_is_owner_scoped(service, postgres_url, catalog):
    repository, redis = catalog
    owner_id, _ = await provision_personal(service, postgres_url)
    execute(postgres_url, "update doctrace.workspaces set plan = 'pro' where id = :id",
            {"id": owner_id})
    workspace = await service.create(owner_id, "Nhóm")
    workspace_id = workspace["id"]
    member_id = auth_user(postgres_url)
    await service.add_member(owner_id, workspace_id, member_id)
    assert [member["user_id"] for member in await service.members(owner_id, workspace_id)] == [
        owner_id, member_id,
    ]

    with pytest.raises(HTTPException) as error:
        await service.assert_owner(member_id, workspace_id)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        redis.zadd(workspace_user_key(workspace_id, member_id), {"first": 1, "second": 2})
        await service.remove_member(owner_id, workspace_id, member_id, repository)
    assert error.value.status_code == 409
    assert error.value.detail["document_count"] == 2
    with pytest.raises(HTTPException) as error:
        await service.remove_member(owner_id, workspace_id, owner_id, repository)
    assert error.value.detail["code"] == "cannot_remove_owner"

    assert (await service.resolve(member_id, workspace_id)).role == "member"
    redis.delete(workspace_user_key(workspace_id, member_id))
    assert (await service.remove_member(owner_id, workspace_id, member_id, repository))["status"] == "removed"
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


async def team_with_member(service, postgres_url):
    owner, _ = await provision_personal(service, postgres_url)
    execute(postgres_url, "update doctrace.workspaces set plan = 'pro' where id = :id", {"id": owner})
    workspace = (await service.create(owner, "Concurrent team"))["id"]
    member = auth_user(postgres_url)
    await service.add_member(owner, workspace, member)
    document = {"doc_id": str(uuid4()), "workspace_id": workspace,
                "owner_user_id": member, "name": "test.pdf", "size_bytes": 100, "storage_key": "fixture"}
    return owner, member, workspace, document


async def wait_for_lock(postgres_url):
    """Wait for an actual competing SQL statement, rather than a timing guess."""
    engine = create_engine(postgres_url)
    try:
        for _ in range(200):
            with engine.connect() as connection:
                waiting = connection.execute(text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND query LIKE '%doctrace.workspace%'"
                )).scalar_one()
            if waiting:
                return
            await asyncio.sleep(0.01)
        pytest.fail("Competing operation did not wait on the admission lock")
    finally:
        engine.dispose()


@pytest.mark.parametrize("operation", ["remove", "archive"])
async def test_upload_commit_finishes_before_member_removal_or_archive(
    service, postgres_url, catalog, monkeypatch, operation,
):
    repository, _ = catalog
    owner, member, workspace, document = await team_with_member(service, postgres_url)
    entered, release = Event(), Event()
    original = repository.create_sync

    def commit(*args, **kwargs):
        entered.set()
        assert release.wait(5), "test did not release upload commit"
        return original(*args, **kwargs)

    monkeypatch.setattr(repository, "create_sync", commit)
    upload = asyncio.create_task(service.create_document(document, repository, limit=5))
    assert await asyncio.to_thread(entered.wait, 5)
    mutate = asyncio.create_task(
        service.remove_member(owner, workspace, member, repository) if operation == "remove"
        else service.archive(owner, workspace)
    )
    try:
        await wait_for_lock(postgres_url)
    finally:
        release.set()
        uploaded, result = await asyncio.gather(upload, mutate, return_exceptions=True)
    assert uploaded["doc_id"] == document["doc_id"]
    assert await repository.count_workspace(workspace, member) == 1
    if operation == "remove":
        assert isinstance(result, HTTPException)
        assert result.detail["code"] == "member_has_documents"
        assert (await service.resolve(member, workspace)).role == "member"
    else:
        assert result["status"] == "archived"


async def test_member_removal_fences_upload_that_previously_passed_auth(
    service, postgres_url, catalog, monkeypatch,
):
    repository, _ = catalog
    owner, member, workspace, document = await team_with_member(service, postgres_url)
    await service.resolve(member, workspace)
    entered, release = Event(), Event()

    def count(*args):
        entered.set()
        assert release.wait(5), "test did not release member removal"
        return 0

    monkeypatch.setattr(repository, "count_workspace_sync", count)
    commit = Mock(wraps=repository.create_sync)
    monkeypatch.setattr(repository, "create_sync", commit)
    remove = asyncio.create_task(service.remove_member(owner, workspace, member, repository))
    assert await asyncio.to_thread(entered.wait, 5)
    upload = asyncio.create_task(service.create_document(document, repository, limit=5))
    try:
        await wait_for_lock(postgres_url)
    finally:
        release.set()
        removed, result = await asyncio.gather(remove, upload, return_exceptions=True)
    assert removed["status"] == "removed"
    assert isinstance(result, HTTPException) and result.status_code == 404
    commit.assert_not_called()
    assert await repository.internal_document(document["doc_id"]) is None


async def test_archived_workspace_rejects_inflight_upload_before_catalog_commit(service, postgres_url, catalog):
    repository, _ = catalog
    owner, member, workspace, document = await team_with_member(service, postgres_url)
    await service.resolve(member, workspace)
    await service.archive(owner, workspace)
    with pytest.raises(HTTPException) as error:
        await service.create_document(document, repository, limit=5)
    assert error.value.status_code == 404
    assert await repository.internal_document(document["doc_id"]) is None


async def test_removal_authorizes_before_count_and_rolls_back_on_redis_failure(
    service, postgres_url, catalog, monkeypatch,
):
    repository, _ = catalog
    owner, member, workspace, _ = await team_with_member(service, postgres_url)
    count = Mock(side_effect=HTTPException(503, "Redis unavailable"))
    monkeypatch.setattr(repository, "count_workspace_sync", count)
    with pytest.raises(HTTPException) as error:
        await service.remove_member(member, workspace, owner, repository)
    assert error.value.status_code == 404
    count.assert_not_called()
    with pytest.raises(HTTPException) as error:
        await service.remove_member(owner, workspace, member, repository)
    assert error.value.status_code == 503
    assert (await service.resolve(member, workspace)).role == "member"


async def test_existing_auth_user_can_join_without_profile_and_rejoin_after_removal(service, postgres_url, catalog):
    repository, _ = catalog
    owner, member, workspace, _ = await team_with_member(service, postgres_url)
    first = await service.add_member(owner, workspace, member)
    assert first == await service.add_member(owner, workspace, member)
    assert (await service.add_member(owner, workspace, owner))["role"] == "owner"
    assert (await service.resolve(owner, workspace)).role == "owner"
    await service.remove_member(owner, workspace, member, repository)
    with pytest.raises(HTTPException) as error:
        await service.resolve(member, workspace)
    assert error.value.status_code == 404
    added = await service.add_member(owner, workspace, member)
    assert added["role"] == "member" and added["status"] == "active"
    assert (await service.resolve(member, workspace)).role == "member"
    with db.session_scope(service.config) as session:
        assert session.execute(text(
            "SELECT removed_at FROM doctrace.workspace_members WHERE workspace_id = :w AND user_id = :u"
        ), {"w": workspace, "u": member}).scalar_one() is None
        assert session.execute(text("SELECT count(*) FROM doctrace.profiles WHERE user_id = :u"),
                               {"u": member}).scalar_one() == 0


@pytest.mark.parametrize("membership", ["new", "active", "removed"])
@pytest.mark.parametrize("deletion", ["soft", "hard"])
async def test_missing_or_deleted_auth_user_never_creates_or_reactivates_membership(
    service, postgres_url, catalog, membership, deletion,
):
    repository, _ = catalog
    owner, member, workspace, _ = await team_with_member(service, postgres_url)
    if membership == "new":
        member = auth_user(postgres_url)
    elif membership == "removed":
        await service.remove_member(owner, workspace, member, repository)
    execute(postgres_url, (
        "UPDATE auth.users SET deleted_at = now() WHERE id = :u" if deletion == "soft"
        else "DELETE FROM auth.users WHERE id = :u"
    ), {"u": member})
    # Neither a stale profile nor an old membership proves Auth-user existence.
    execute(postgres_url, "INSERT INTO doctrace.profiles (user_id) VALUES (:u)", {"u": member})
    with pytest.raises(HTTPException) as error:
        await service.add_member(owner, workspace, member)
    assert error.value.status_code == 404
    assert error.value.detail["code"] == "member_user_not_found"
    with db.session_scope(service.config) as session:
        status = session.execute(text(
            "SELECT status FROM doctrace.workspace_members WHERE workspace_id = :w AND user_id = :u"
        ), {"w": workspace, "u": member}).scalar_one_or_none()
    assert status == (None if membership == "new" else membership)


async def test_member_add_authorizes_before_auth_lookup_and_fails_closed_on_lookup_failure(service, postgres_url):
    owner, member, workspace, _ = await team_with_member(service, postgres_url)
    execute(postgres_url, "REVOKE EXECUTE ON FUNCTION doctrace.auth_user_exists(uuid) FROM doctrace_app")
    try:
        for caller, target_workspace in ((member, workspace), (str(uuid4()), workspace), (owner, str(uuid4()))):
            with pytest.raises(HTTPException) as error:
                await service.add_member(caller, target_workspace, str(uuid4()))
            assert error.value.status_code == 404
            assert error.value.detail["code"] == "workspace_not_found"
        with pytest.raises(HTTPException) as error:
            await service.add_member(owner, workspace, str(uuid4()))
        assert error.value.status_code == 503
        assert error.value.detail["code"] == "workspace_unavailable"
        await service.archive(owner, workspace)
        with pytest.raises(HTTPException) as error:
            await service.add_member(owner, workspace, member)
        assert error.value.detail["code"] == "workspace_not_found"
    finally:
        execute(postgres_url, "GRANT EXECUTE ON FUNCTION doctrace.auth_user_exists(uuid) TO doctrace_app")
