"""Workspace header validation, management routes and error contracts."""
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.errors import api_error
from app.core.workspace import require_workspace
from app.main import app
from app.services.workspaces import (
    WorkspaceContext, WorkspaceService, get_workspace_service,
)

USER = "00000000-0000-0000-0000-000000000001"
WORKSPACE = "00000000-0000-0000-0000-0000000000ab"
MEMBER = "00000000-0000-0000-0000-000000000002"


def context(**overrides):
    values = {
        "workspace_id": WORKSPACE, "user_id": USER, "role": "owner",
        "plan": "free", "kind": "personal", "name": "Cá nhân",
    }
    values.update(overrides)
    return WorkspaceContext(**values)


@pytest.fixture
def service():
    fake = AsyncMock(spec=WorkspaceService)
    app.dependency_overrides[get_workspace_service] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_workspace_service, None)


def test_api_error_has_a_stable_code_and_extra_fields():
    error = api_error(409, "member_has_documents", "Còn tài liệu.", document_count=2)
    assert error.status_code == 409
    assert error.detail == {
        "code": "member_has_documents", "message": "Còn tài liệu.", "document_count": 2,
    }


@pytest.mark.parametrize("header", [None, "", "   "])
async def test_missing_workspace_header_is_a_client_error(header):
    with pytest.raises(HTTPException) as error:
        await require_workspace(user={"id": USER}, x_workspace_id=header,
                                service=AsyncMock(spec=WorkspaceService))
    assert error.value.status_code == 400
    assert error.value.detail["code"] == "workspace_required"


async def test_malformed_workspace_header_is_rejected_before_database_access():
    fake = AsyncMock(spec=WorkspaceService)
    with pytest.raises(HTTPException) as error:
        await require_workspace(user={"id": USER}, x_workspace_id="not-a-uuid", service=fake)
    assert error.value.status_code == 400
    assert error.value.detail["code"] == "workspace_invalid"
    fake.resolve.assert_not_awaited()


async def test_valid_header_returns_the_verified_membership_context():
    fake = AsyncMock(spec=WorkspaceService)
    fake.resolve.return_value = context()
    result = await require_workspace(user={"id": USER}, x_workspace_id=WORKSPACE, service=fake)
    assert result.workspace_id == WORKSPACE
    assert result.user_id == USER
    fake.resolve.assert_awaited_once_with(USER, WORKSPACE)


def test_list_and_create_workspaces(client, service):
    service.list_for_user.return_value = [{"id": WORKSPACE, "role": "owner", "status": "active"}]
    response = client.get("/api/workspaces")
    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == WORKSPACE
    service.list_for_user.assert_awaited_once_with(USER)

    service.create.return_value = {"id": str(uuid4()), "name": "Team", "role": "owner"}
    response = client.post("/api/workspaces", json={"name": "  Team  "})
    assert response.status_code == 201
    service.create.assert_awaited_once_with(USER, "Team")


@pytest.mark.parametrize("payload", [{}, {"name": ""}, {"name": "x" * 81}, {"name": "Team", "plan": "pro"}])
def test_invalid_workspace_create_payload_never_reaches_the_service(client, service, payload):
    assert client.post("/api/workspaces", json=payload).status_code == 422
    service.create.assert_not_awaited()


def test_member_management_is_owner_metadata_only(client, service):
    service.members.return_value = [{"user_id": MEMBER, "role": "member", "email": "m@example.test"}]
    response = client.get(f"/api/workspaces/{WORKSPACE}/members")
    assert response.status_code == 200
    assert response.json()["items"][0]["user_id"] == MEMBER
    service.members.assert_awaited_once_with(USER, WORKSPACE)

    service.add_member.return_value = {"user_id": MEMBER, "role": "member"}
    response = client.post(f"/api/workspaces/{WORKSPACE}/members", json={"user_id": MEMBER})
    assert response.status_code == 201
    service.add_member.assert_awaited_once_with(USER, WORKSPACE, MEMBER)


def test_removing_a_member_passes_the_document_count_to_the_service(client, service, repository):
    repository.count_workspace = AsyncMock(return_value=3)
    service.remove_member.side_effect = api_error(
        409, "member_has_documents", "Thành viên còn tài liệu chưa xóa trong workspace.",
        document_count=3,
    )
    response = client.delete(f"/api/workspaces/{WORKSPACE}/members/{MEMBER}")
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "member_has_documents",
        "message": "Thành viên còn tài liệu chưa xóa trong workspace.",
        "document_count": 3,
    }
    service.assert_owner.assert_awaited_once_with(USER, WORKSPACE)
    repository.count_workspace.assert_awaited_once_with(WORKSPACE, MEMBER)
    service.remove_member.assert_awaited_once_with(USER, WORKSPACE, MEMBER, 3)


def test_removing_a_clean_member_checks_owner_first(client, service, repository):
    repository.count_workspace = AsyncMock(return_value=0)
    service.remove_member.return_value = {"user_id": MEMBER, "status": "removed"}
    response = client.delete(f"/api/workspaces/{WORKSPACE}/members/{MEMBER}")
    assert response.status_code == 200
    service.assert_owner.assert_awaited_once_with(USER, WORKSPACE)
    service.remove_member.assert_awaited_once_with(USER, WORKSPACE, MEMBER, 0)


def test_non_owner_cannot_probe_workspace_document_counts(client, service, repository):
    repository.count_workspace = AsyncMock()
    service.assert_owner.side_effect = api_error(404, "workspace_not_found", "Không tìm thấy workspace.")
    response = client.delete(f"/api/workspaces/{WORKSPACE}/members/{MEMBER}")
    assert response.status_code == 404
    repository.count_workspace.assert_not_awaited()
    service.remove_member.assert_not_awaited()


def test_archive_and_restore_use_the_service(client, service):
    service.archive.return_value = {"id": WORKSPACE, "status": "archived"}
    service.restore.return_value = {"id": WORKSPACE, "status": "active"}
    assert client.post(f"/api/workspaces/{WORKSPACE}/archive").json()["status"] == "archived"
    service.archive.assert_awaited_once_with(USER, WORKSPACE)
    assert client.post(f"/api/workspaces/{WORKSPACE}/restore").json()["status"] == "active"
    service.restore.assert_awaited_once_with(USER, WORKSPACE)
