"""Real auth dependency, bounded upload admission, and lightweight liveness."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from anyio import CapacityLimiter
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core import auth
from app.core.limits import require_upload_slot
from app.main import app


def test_protected_endpoints_require_auth_without_fixture_override():
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"query": "q", "doc_id": "doc"})
        assert response.status_code == 401
        response = client.post("/api/upload", files={"file": ("doc.pdf", b"pdf", "application/pdf")})
        assert response.status_code == 401
        assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("upstream_status", [200, 401])
async def test_auth_validates_bearer_with_supabase(monkeypatch, upstream_status):
    monkeypatch.setattr(auth, "get_config", lambda: SimpleNamespace(
        supabase_url="https://example.supabase.co", supabase_publishable_key="public-test-key",
    ))
    get = AsyncMock(return_value=httpx.Response(upstream_status, json={"id": "verified-user"}))
    client = AsyncMock()
    client.__aenter__.return_value.get = get
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kwargs: client)
    if upstream_status == 200:
        assert (await auth.require_supabase_user("Bearer test-access-token"))["id"] == "verified-user"
    else:
        with pytest.raises(HTTPException) as error:
            await auth.require_supabase_user("Bearer test-access-token")
        assert error.value.status_code == 401
    get.assert_awaited_once_with("https://example.supabase.co/auth/v1/user", headers={
        "Authorization": "Bearer test-access-token", "apikey": "public-test-key",
    })


async def test_upload_capacity_rejects_excess_and_releases_after_failure():
    limiter = CapacityLimiter(1)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(upload_limiter=limiter)))
    # Occupy capacity as a different request/task.
    limiter.acquire_on_behalf_of_nowait("another-upload")
    denied = require_upload_slot(request)
    with pytest.raises(HTTPException) as error:
        await anext(denied)
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "5"
    limiter.release_on_behalf_of("another-upload")
    admitted = require_upload_slot(request)
    await anext(admitted)
    assert limiter.borrowed_tokens == 1
    with pytest.raises(RuntimeError, match="indexing failed"):
        await admitted.athrow(RuntimeError("indexing failed"))
    assert limiter.borrowed_tokens == 0
