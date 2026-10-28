"""Opt-in error reporting with a content-free, allow-listed event envelope.

SDK integrations may collect SQL, request data, exception values or job args.
Rebuild the outgoing event instead of trying to enumerate sensitive fields.
Tracing, profiling, logs, breadcrumbs and local variables are disabled.
"""
import logging
from pathlib import Path
import re

from app.core.config import AppConfig
from app.core.observability import LOG_EVENTS, current_request_id, log_context, valid_request_id


def _symbol(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.<>-]{1,128}", value) else "unknown"


def scrub_event(event, hint):
    clean = {key: event[key] for key in ("event_id", "timestamp", "platform", "release", "environment", "level") if key in event}
    record = hint.get("log_record")
    clean["message"] = (record.msg if record and record.name.startswith("app.")
                        and isinstance(record.msg, str) and record.msg in LOG_EVENTS else "application_error")
    clean["tags"] = {}
    request_id = current_request_id()
    if valid_request_id(request_id):
        clean["tags"]["request_id"] = request_id
    for key in ("workspace_id", "user_id", "doc_id", "job_id", "attempt"):
        value = log_context.get().get(key)
        if value is not None and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(value)):
            clean["tags"][key] = str(value)
    values = []
    for exc in event.get("exception", {}).get("values", [])[-5:]:
        frames = []
        for frame in exc.get("stacktrace", {}).get("frames", [])[-12:]:
            frames.append({"filename": _symbol(Path(str(frame.get("filename", ""))).name),
                           "function": _symbol(frame.get("function")),
                           "lineno": frame.get("lineno") if type(frame.get("lineno")) is int else 0})
        values.append({"type": _symbol(exc.get("type")), "value": "Details redacted",
                       "stacktrace": {"frames": frames}})
    if values:
        clean["exception"] = {"values": values}
    return clean


def configure_sentry(config: AppConfig) -> None:
    if not config.sentry_dsn:
        return
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.redis import RedisIntegration
    from sentry_sdk.integrations.rq import RqIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

    sentry_sdk.init(
        dsn=config.sentry_dsn, environment=config.sentry_environment, release=config.sentry_release,
        default_integrations=False, auto_enabling_integrations=False,
        integrations=[FastApiIntegration(), StarletteIntegration(), RqIntegration(),
                      RedisIntegration(), SqlalchemyIntegration(), LoggingIntegration(level=None, event_level=logging.ERROR)],
        send_default_pii=False, include_local_variables=False, max_request_body_size="never",
        max_breadcrumbs=0, traces_sample_rate=0.0, profiles_sample_rate=0.0, enable_logs=False,
        before_send=scrub_event, before_send_transaction=lambda event, hint: None,
        before_breadcrumb=lambda breadcrumb, hint: None,
    )
