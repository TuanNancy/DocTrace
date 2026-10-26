"""Real API/SSE routes with local auth/RAG fixtures; never shipped in the API image."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import uvicorn
from fastapi import HTTPException, Request

from app.core.auth import require_supabase_user
from app.core.workspace import require_workspace
from app.main import app
from app.routers import chat
from app.services.document_repository import get_document_repository
from app.services.quotas import get_quota_service
from app.services.workspaces import WorkspaceContext

pipelines = []
PROXY_WORKSPACE = "11111111-1111-4111-8111-111111111111"


async def test_user(request: Request):
    if request.headers.get("authorization") != "Bearer proxy-test-token":
        raise HTTPException(status_code=401, detail="Test token required")
    return {"id": "proxy-test-user"}


async def test_workspace(request: Request) -> WorkspaceContext:
    # Fail when Nginx drops the tenant header instead of silently bypassing a
    # contract the browser must satisfy on every workspace-scoped request.
    if request.headers.get("x-workspace-id") != PROXY_WORKSPACE:
        raise HTTPException(status_code=400, detail="X-Workspace-Id was not forwarded")
    return WorkspaceContext(
        workspace_id=PROXY_WORKSPACE, user_id="proxy-test-user",
        role="owner", plan="free", kind="personal", name="Proxy test",
    )


class TestPipeline:
    def __init__(self):
        self.gate = asyncio.Event()
        self.active = True

    async def retrieve_chunks(self, *args, **kwargs):
        return [SimpleNamespace(chunk_id="chunk", page=1, source="fixture.pdf", score=0.9)]

    def select_context_chunks(self, chunks):
        return chunks

    async def stream_answer(self, **kwargs):
        yield "first"
        # The test releases the gate only AFTER seeing the first token through Nginx.
        # A buffering proxy deadlocks here and fails the client read timeout.
        await self.gate.wait()
        yield "last"

    async def shutdown(self):
        self.active = False


async def create_pipeline(**kwargs):
    pipeline = TestPipeline()
    pipelines.append(pipeline)
    return pipeline


app.dependency_overrides[require_supabase_user] = test_user


class TestDocuments:
    async def get(self, workspace_id, user_id, doc_id):
        return {"status": "ready", "active_index_id": doc_id}


app.dependency_overrides[get_document_repository] = TestDocuments
app.dependency_overrides[require_workspace] = test_workspace
chat.create_initialized_rag_pipeline = create_pipeline


class TestQuotas:
    """Admit without Postgres; proxy verification has no control plane."""

    async def existing_chat(self, workspace_id, user_id, request_id):
        return None

    async def admit_chat(self, workspace_id, user_id, request_id, doc_id, plan):
        return {"chat_request_id": str(uuid4()), "used": 1, "limit": 10}

    async def mark_chat_status(self, chat_request_id, status, error_code=None):
        return True


app.dependency_overrides[get_quota_service] = TestQuotas


@app.get("/__probe")
async def probe(request: Request):
    return {
        "authorization": request.headers.get("authorization"),
        "forwarded_for": request.headers.get("x-forwarded-for"),
        "scheme": request.url.scheme,
        "host": request.headers.get("host"),
        "active": sum(pipeline.active for pipeline in pipelines),
    }


@app.post("/__release")
async def release():
    for pipeline in pipelines:
        pipeline.gate.set()
    return {"released": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, proxy_headers=True, forwarded_allow_ips="*")
