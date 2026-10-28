"""Request correlation, structured access logs and JSON log formatting."""
from __future__ import annotations

from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import time
import traceback
from typing import Any
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_LOG_FIELDS = (
    "event", "method", "path", "status_code", "duration_ms", "workspace_id",
    "user_id", "doc_id", "job_id", "attempt", "route", "model", "cache_hit", "error_code",
    "kind", "chunks_count", "count",
)
# Message text and formatting arguments are never emitted. Only these code-owned
# event names can become log messages, including in the human-readable formatter.
LOG_EVENTS = frozenset({
    "http_request", "http_request_failed", "document_job_started", "document_job_completed",
    "document_job_failed", "document_pdf_rejected", "database_probe_failed", "redis_probe_failed",
    "quota_operation_failed", "transcript_operation_failed", "workspace_operation_failed",
    "provider_reconciliation_failed", "provider_persistence_failed", "provider_generation_failed",
    "chat_status_write_failed", "chat_transcript_write_failed", "chat_stream_failed", "chat_failed",
    "pdf_retention_failed", "pdf_cleanup_failed", "enqueue_confirmation_failed", "enqueue_reconcile_failed",
    "pdf_load_failed", "pdf_scanned", "pdf_chunked", "pdf_index_cleanup_failed",
    "embedding_probe_failed", "embedding_dimension_changed", "provider_no_choices", "provider_call_failed", "provider_stream_failed",
    "vector_status_failed", "rag_provider_created", "rag_store_created", "rag_initialized",
    "rag_shutdown", "rag_retrieved", "rag_stream_failed", "transcripts_purged", "transcript_purge_failed",
    "admin_operation_failed", "failure_persistence_failed", "admin_health_failed",
    "workspace_purge_failed",
})

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")
log_context: ContextVar[dict] = ContextVar("log_context", default={})
request_logger = logging.getLogger("app.request")


def valid_request_id(value: str | None) -> bool:
    return bool(value and _REQUEST_ID.fullmatch(value))


def current_request_id() -> str:
    return request_id_context.get()


@contextmanager
def bind_log_context(*, request_id: str | None = None, **fields):
    """Task-local context, also propagated by AnyIO to blocking worker threads."""
    request_token = request_id_context.set(request_id if valid_request_id(request_id) else "-")
    fields_token = log_context.set({**log_context.get(), **fields})
    try:
        yield
    finally:
        log_context.reset(fields_token)
        request_id_context.reset(request_token)


def _safe_field(key: str, value: Any) -> Any:
    if isinstance(value, (int, float, bool)):
        return value
    if not isinstance(value, str):
        return None
    if key in ("path", "route"):
        return value if re.fullmatch(r"/[A-Za-z0-9_/{\}-]*", value) else "<unmatched>"
    return value if re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", value) else None


def safe_log_payload(record: logging.LogRecord) -> dict:
    trusted = record.name.startswith("app.") and isinstance(record.msg, str) and record.msg in LOG_EVENTS
    event = record.msg if trusted else "external_log"
    payload: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": record.levelname,
        "logger": record.name,
        "message": event,
        "request_id": current_request_id() if valid_request_id(current_request_id()) else "-",
    }
    if trusted:
        request_id = getattr(record, "request_id", None) or current_request_id()
        payload["request_id"] = request_id if valid_request_id(request_id) else "-"
        for key in _LOG_FIELDS:
            value = _safe_field(key, getattr(record, key, log_context.get().get(key)))
            if value is not None:
                payload[key] = value
    if record.exc_info and record.exc_info[0]:
        # SQL/HTTP exceptions may contain whole rows, prompts and signed URLs.
        # Retain code locations and exception class; never value, locals, source
        # lines, chained exception messages, stack_info or cached exc_text.
        payload["exception_type"] = record.exc_info[0].__name__
        payload["frames"] = [
            {"file": Path(frame.f_code.co_filename).name, "function": frame.f_code.co_name, "line": line}
            for frame, line in traceback.walk_tb(record.exc_info[2])
        ][-12:]
    return payload


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(safe_log_payload(record), ensure_ascii=False)


class SafeTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return " ".join(f"{key}={json.dumps(value, ensure_ascii=False)}"
                        for key, value in safe_log_payload(record).items())


def configure_logging(config, *, install_root: bool = False) -> None:
    """Apply the same privacy boundary to app, SDK, Uvicorn and RQ logs."""
    level = getattr(logging, config.log_level, logging.INFO)
    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)
    root = logging.getLogger()
    formatter = JsonFormatter() if config.log_json else SafeTextFormatter()
    if config.log_json or (install_root and not root.handlers):
        handler = logging.StreamHandler()
        root.handlers[:] = [handler]
    # API imports under Uvicorn may precede root logging setup.
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    for handler in root.handlers:
        handler.setFormatter(formatter)
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "rq.worker", "rq.job"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    # Our request middleware records route templates, without raw URLs/queries.
    logging.getLogger("uvicorn.access").disabled = True


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
    return path or "<unmatched>"


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
