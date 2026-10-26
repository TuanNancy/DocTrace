"""Request correlation, structured access logs and JSON log formatting."""
from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import re
import time
from typing import Any
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_LOG_FIELDS = (
    "event", "method", "path", "status_code", "duration_ms", "workspace_id",
    "user_id", "doc_id", "job_id", "attempt", "route", "model", "cache_hit", "error_code",
)

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")
request_logger = logging.getLogger("app.request")


def valid_request_id(value: str | None) -> bool:
    return bool(value and _REQUEST_ID.fullmatch(value))


def current_request_id() -> str:
    return request_id_context.get()


class JsonFormatter(logging.Formatter):
    """Allow-listed fields only; prompts, headers and query strings never leak."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_context.get(),
        }
        for key in _LOG_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(config, *, install_root: bool = False) -> None:
    """Configure app logs without stealing pytest/uvicorn handlers by default."""
    level = getattr(logging, config.log_level, logging.INFO)
    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)
    root = logging.getLogger()
    if config.log_json:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root.handlers[:] = [handler]
        root.setLevel(level)
    elif install_root and not root.handlers:
        logging.basicConfig(level=level)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", ()):
        if key.lower() == name:
            try:
                return value.decode("latin-1")
            except UnicodeDecodeError:
                return None
    return None


def _route_path(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path or scope.get("path", "")


class RequestContextMiddleware:
    """Generate/validate X-Request-ID, bind it for logs and echo it back."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied = _header(scope, REQUEST_ID_HEADER.lower().encode())
        request_id = supplied if valid_request_id(supplied) else str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_context.set(request_id)
        status_code: int | None = None

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        started = time.perf_counter()
        failed = False
        try:
            await self.app(scope, receive, send_with_request_id)
        except BaseException:
            failed = True
            raise
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            if failed:
                request_logger.exception(
                    "http_request_failed",
                    extra={"request_id": request_id, "method": scope.get("method"),
                           "path": _route_path(scope), "status_code": 500,
                           "duration_ms": duration_ms},
                )
            else:
                request_logger.info(
                    "http_request",
                    extra={"request_id": request_id, "method": scope.get("method"),
                           "path": _route_path(scope), "status_code": status_code,
                           "duration_ms": duration_ms},
                )
            request_id_context.reset(token)
