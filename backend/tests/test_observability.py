"""Request correlation, log redaction and readiness behavior."""
import json
import logging
import uuid

from fastapi.testclient import TestClient

from app.core.observability import (
    JsonFormatter, configure_logging, request_id_context, valid_request_id,
)
from app.main import app


def test_request_id_is_preserved_and_always_returned(client):
    response = client.get("/health", headers={"X-Request-ID": "test-request.123"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request.123"


def test_missing_or_invalid_request_id_is_replaced_with_uuid(client):
    for headers in ({}, {"X-Request-ID": "has spaces"}):
        response = client.get("/health", headers=headers)
        generated = response.headers["X-Request-ID"]
        assert uuid.UUID(generated)
        assert valid_request_id(generated)
        assert generated != "has spaces"


def test_json_logger_uses_context_and_drops_unlisted_fields():
    token = request_id_context.set("request-from-context")
    try:
        record = logging.LogRecord(
            "app.request", logging.INFO, __file__, 1, "http_request", (), None,
        )
        record.method = "GET"
        record.path = "/ready"
        record.status_code = 503
        record.duration_ms = 1.2
        record.authorization = "Bearer private"
        record.query = "private prompt"
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_context.reset(token)
    assert payload["request_id"] == "request-from-context"
    assert (payload["method"], payload["path"], payload["status_code"]) == ("GET", "/ready", 503)
    assert "authorization" not in payload
    assert "private" not in json.dumps(payload)


def test_plain_logging_leaves_existing_root_handlers():
    root = logging.getLogger()
    before = list(root.handlers)
    configure_logging(type("Config", (), {"log_level": "INFO", "log_json": False})())
    assert root.handlers == before


def test_ready_reports_dependency_state(monkeypatch):
    async def healthy():
        return "ok", {
            "redis": {"status": "ok", "latency_ms": 1},
            "database": {"status": "disabled", "latency_ms": None},
        }

    monkeypatch.setattr("app.main.readiness", healthy)
    with TestClient(app) as test_client:
        response = test_client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["database"]["status"] == "disabled"
    assert response.headers["Cache-Control"] == "no-store"


def test_ready_fails_closed_when_a_dependency_errors(monkeypatch):
    async def unhealthy():
        return "degraded", {
            "redis": {"status": "error", "error_code": "redis_unavailable"},
            "database": {"status": "ok", "latency_ms": 1},
        }

    monkeypatch.setattr("app.main.readiness", unhealthy)
    with TestClient(app) as test_client:
        response = test_client.get("/ready")
        assert test_client.get("/health").json() == {"status": "ok"}
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
