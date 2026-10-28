"""Owner-scoped transcript routes and citation staleness."""
from uuid import uuid4

from app.core.workspace import require_workspace
from app.main import app
from app.services.workspaces import WorkspaceContext

OWNER = "00000000-0000-0000-0000-000000000001"
WORKSPACE = "00000000-0000-0000-0000-0000000000ab"
CONVERSATION = "00000000-0000-0000-0000-0000000000c3"
DOC = str(uuid4())


def conversation(active_index_id: str | None = DOC) -> dict:
    return {
        "id": CONVERSATION, "workspace_id": WORKSPACE, "doc_id": DOC,
        "created_at": "2026-10-26T00:00:00Z", "updated_at": "2026-10-26T00:01:00Z",
        "messages": [
            {
                "id": "m1", "role": "user", "content": "Câu hỏi", "sources": [],
                "index_id": None, "status": "complete",
                "created_at": "2026-10-26T00:00:00Z", "updated_at": "2026-10-26T00:00:00Z",
            },
            {
                "id": "m2", "role": "assistant", "content": "Trả lời", "index_id": DOC,
                "status": "complete", "created_at": "2026-10-26T00:00:01Z",
                "updated_at": "2026-10-26T00:00:01Z",
                "sources": [{
                    "citation_id": 1, "chunk_id": "chunk-1", "doc_id": DOC,
                    "page": 2, "source": "sample.pdf", "score": 0.9,
                }],
            },
        ],
    }


def test_list_scopes_to_workspace_user_document_and_limit(client, transcripts):
    response = client.get(f"/api/conversations?doc_id={DOC}&limit=5")

    assert response.status_code == 200
    assert response.json() == {"items": []}
    transcripts.list.assert_awaited_once_with(WORKSPACE, OWNER, DOC, 5)


def test_get_marks_sources_stale_after_reindex(client, transcripts, repository):
    transcripts.get.return_value = conversation()
    repository.transcript_documents.side_effect = None
    repository.transcript_documents.return_value = {DOC: {"status": "ready", "active_index_id": str(uuid4())}}

    response = client.get(f"/api/conversations/{CONVERSATION}")

    assert response.status_code == 200
    body = response.json()
    assert body["messages"][1]["stale"] is True
    assert body["messages"][1]["sources"][0]["stale"] is True
    transcripts.get.assert_awaited_once_with(WORKSPACE, OWNER, CONVERSATION)
    repository.transcript_documents.assert_awaited_once_with(WORKSPACE, OWNER, [DOC])


def test_get_keeps_current_generation_sources_usable(client, transcripts, repository):
    transcripts.get.return_value = conversation()
    repository.transcript_documents.side_effect = None
    repository.transcript_documents.return_value = {DOC: {"status": "ready", "active_index_id": DOC}}

    body = client.get(f"/api/conversations/{CONVERSATION}").json()

    assert body["messages"][1]["stale"] is False
    assert body["messages"][1]["sources"][0]["stale"] is False


def test_missing_or_deleting_document_hides_transcript_even_before_sql_retention(
    client, transcripts, repository,
):
    transcripts.get.return_value = conversation()
    repository.transcript_documents.side_effect = None
    repository.transcript_documents.return_value = {}

    response = client.get(f"/api/conversations/{CONVERSATION}")

    assert response.status_code == 404
    assert "messages" not in response.json()


def test_list_omits_deleting_documents_even_before_sql_retention(client, transcripts, repository):
    transcripts.list.return_value = {"items": [{"id": CONVERSATION, "doc_id": DOC}]}
    repository.transcript_documents.side_effect = None
    repository.transcript_documents.return_value = {}
    response = client.get("/api/conversations")
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_get_does_not_reveal_another_users_conversation(client, transcripts):
    transcripts.get.return_value = None

    response = client.get(f"/api/conversations/{CONVERSATION}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "conversation_not_found"


def test_delete_is_owner_scoped_and_returns_204(client, transcripts):
    transcripts.delete.return_value = True
    response = client.delete(f"/api/conversations/{CONVERSATION}")
    assert response.status_code == 204
    transcripts.delete.assert_awaited_once_with(WORKSPACE, OWNER, CONVERSATION)

    transcripts.delete.return_value = False
    missing = client.delete(f"/api/conversations/{CONVERSATION}")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "conversation_not_found"


def test_member_uses_their_own_identity_for_transcript_queries(client, transcripts):
    async def member():
        return WorkspaceContext(
            workspace_id=WORKSPACE, user_id="00000000-0000-0000-0000-000000000002",
            role="member", plan="free", kind="team", name="Nhóm",
        )

    original = app.dependency_overrides[require_workspace]
    app.dependency_overrides[require_workspace] = member
    try:
        assert client.get("/api/conversations").status_code == 200
    finally:
        app.dependency_overrides[require_workspace] = original

    transcripts.list.assert_awaited_once_with(
        WORKSPACE, "00000000-0000-0000-0000-000000000002", None, 20,
    )
