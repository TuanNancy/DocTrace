"""Request correlation, log redaction and readiness behavior."""
import json
import logging
import sys
import uuid

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

from app.core.observability import (
    JsonFormatter, SafeTextFormatter, configure_logging, request_id_context, valid_request_id,
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
            "database": {"status": "ok", "latency_ms": 1},
        }

    monkeypatch.setattr("app.main.readiness", healthy)
    with TestClient(app) as test_client:
        response = test_client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["database"]["status"] == "ok"
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


@pytest.mark.parametrize("state", ["disabled", "error", "unknown", None])
async def test_readiness_requires_affirmative_database_status(monkeypatch, state):
    from app.services import readiness as probes
    monkeypatch.setattr(probes, "check_redis", AsyncMock(return_value={"status": "ok"}))
    monkeypatch.setattr(probes, "check_database", AsyncMock(return_value={"status": state}))
    status, _ = await probes.readiness()
    assert status == "degraded"


@pytest.mark.parametrize("formatter", [JsonFormatter(), SafeTextFormatter()])
@pytest.mark.parametrize("name,message", [
    ("app.routers.chat", "chat_stream_failed"),
    ("app.routers.chat", "private-prompt %s"),
    ("sqlalchemy.engine", "private SQL %s"),
    ("rq.worker", "job failed %s"),
    ("httpx", "https://storage.test/private.pdf?token=secret"),
])
def test_all_log_sinks_drop_messages_arguments_and_exception_values(formatter, name, message):
    try:
        raise ValueError("private-transcript https://storage.test/private.pdf?token=secret")
    except ValueError:
        record = logging.LogRecord(name, logging.ERROR, __file__, 1, message,
                                   ("Bearer secret",), sys.exc_info())
    record.exc_text = "cached private exception"
    record.stack_info = "private source line"
    record.body = {"prompt": "private-body"}
    rendered = formatter.format(record)
    for value in ("private-prompt", "private-transcript", "private.pdf", "Bearer", "secret", "private SQL", "cached private", "private source", "private-body"):
        assert value not in rendered
    assert "ValueError" in rendered
    assert "test_all_log_sinks" in rendered


def test_unknown_route_does_not_log_user_supplied_path_or_query(client, caplog):
    with caplog.at_level(logging.INFO, logger="app.request"):
        response = client.get("/private-document-title?token=secret")
    assert response.status_code == 404
    record = next(r for r in caplog.records if r.msg == "http_request")
    payload = JsonFormatter().format(record)
    assert "private-document" not in payload
    assert "secret" not in payload
    assert "unmatched" in payload


def test_unhandled_error_preserves_request_id_and_hides_exception(monkeypatch):
    async def failure():
        raise RuntimeError("private-database-password")
    monkeypatch.setattr("app.main.readiness", failure)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/ready", headers={"X-Request-ID": "failed-request"})
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "failed-request"
    assert "private" not in response.text
