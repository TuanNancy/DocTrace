"""GET /api/usage merges Postgres counters with the Redis document catalog."""
from app.core.workspace import require_workspace
from app.main import app
from app.services.workspaces import WorkspaceContext


def test_usage_merges_workspace_document_count(client, quotas, repository):
    quotas.usage.return_value = {
        **quotas.usage.return_value,
        "chat": {"used": 4, "limit": 10, "remaining": 6, "metric": "chat_questions_month"},
        "documents": {"used": 0, "limit": 5, "remaining": 5, "metric": "documents"},
    }
    repository.count_workspace.return_value = 3

    response = client.get("/api/usage")

    assert response.status_code == 200
    body = response.json()
    assert body["chat"]["used"] == 4
    assert body["chat"]["remaining"] == 6
    assert body["documents"] == {
        "used": 3, "limit": 5, "remaining": 2, "metric": "documents",
    }
    quotas.usage.assert_awaited_once_with(
        "00000000-0000-0000-0000-0000000000ab", "free",
        "00000000-0000-0000-0000-000000000001", "owner",
    )
    repository.count_workspace.assert_awaited_once_with(
        "00000000-0000-0000-0000-0000000000ab",
    )


def test_usage_remaining_never_goes_negative(client, quotas, repository):
    quotas.usage.return_value = {
        **quotas.usage.return_value,
        "documents": {"used": 0, "limit": 2, "remaining": 2, "metric": "documents"},
    }
    repository.count_workspace.return_value = 7

    body = client.get("/api/usage").json()

    assert body["documents"]["remaining"] == 0


def test_member_usage_never_reads_workspace_document_total(client, quotas, repository):
    async def member():
        return WorkspaceContext(
            workspace_id="00000000-0000-0000-0000-0000000000ab",
            user_id="00000000-0000-0000-0000-000000000002",
            role="member", plan="pro", kind="team", name="Nhóm",
        )

    original = app.dependency_overrides.get(require_workspace)
    app.dependency_overrides[require_workspace] = member
    repository.count_workspace.return_value = 2
    try:
        response = client.get("/api/usage")
        assert response.status_code == 200
        assert response.json()["documents"]["used"] == 2
        assert response.json()["documents"]["remaining"] is None
    finally:
        app.dependency_overrides[require_workspace] = original

    quotas.usage.assert_awaited_once_with(
        "00000000-0000-0000-0000-0000000000ab", "pro",
        "00000000-0000-0000-0000-000000000002", "member",
    )
    repository.count_workspace.assert_awaited_once_with(
        "00000000-0000-0000-0000-0000000000ab", "00000000-0000-0000-0000-000000000002",
    )


def test_usage_does_not_hide_a_catalog_outage(client, repository):
    from fastapi import HTTPException

    repository.count_workspace.side_effect = HTTPException(503, "Redis unavailable")
    assert client.get("/api/usage").status_code == 503
