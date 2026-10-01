"""Real API/SSE routes with local auth/RAG fixtures; never shipped in the API image."""
import asyncio
from types import SimpleNamespace

import uvicorn
from fastapi import HTTPException, Request

from app.core.auth import require_supabase_user
from app.main import app
from app.routers import chat

pipelines = []


async def test_user(request: Request):
    if request.headers.get("authorization") != "Bearer proxy-test-token":
        raise HTTPException(status_code=401, detail="Test token required")
    return {"id": "proxy-test-user"}


class TestPipeline:
    def __init__(self):
        self.gate = asyncio.Event()
        self.active = True

    async def retrieve_chunks(self, *args, **kwargs):
        return [SimpleNamespace(page=1, source="fixture.pdf", score=0.9)]

    async def stream_answer(self, **kwargs):
        yield "first"
        # The test releases the gate only AFTER seeing the first token through Nginx.
        # A buffering proxy deadlocks here and fails the client read timeout.
        await self.gate.wait()
        yield "last"

    async def shutdown(self):
        self.active = False


async def create_pipeline():
    pipeline = TestPipeline()
    pipelines.append(pipeline)
    return pipeline


app.dependency_overrides[require_supabase_user] = test_user
chat.create_initialized_rag_pipeline = create_pipeline


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
