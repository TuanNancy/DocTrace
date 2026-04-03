"""
Pytest fixtures: FastAPI TestClient and app.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure backend app is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.auth import require_supabase_user
from app.main import app


async def _fake_supabase_user():
    return {"id": "00000000-0000-0000-0000-000000000001", "email": "test@example.com"}


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient for router tests."""
    app.dependency_overrides[require_supabase_user] = _fake_supabase_user
    yield TestClient(app)
    app.dependency_overrides.pop(require_supabase_user, None)
