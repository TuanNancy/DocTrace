import json
import logging

import sentry_sdk
from sentry_sdk.transport import Transport

from app.core.config import AppConfig
from app.core.observability import bind_log_context
from app.core.sentry import configure_sentry, scrub_event


def test_scrubber_rebuilds_an_allowlisted_event():
    secret = "PRIVATE prompt https://signed.example/pdf?token=secret Bearer abc"
    event = {"event_id": "a" * 32, "level": "error", "message": secret, "request": {"headers": secret, "data": secret},
             "user": {"email": secret}, "extra": {"job_args": secret}, "breadcrumbs": [{"message": secret}],
             "contexts": {"sql": secret}, "transaction": secret, "spans": [{"description": secret}],
             "exception": {"values": [{"type": "ValueError", "value": secret, "stacktrace": {"frames": [
                 {"filename": "/private/developer/app/main.py", "function": "run", "lineno": 42,
                  "vars": {"pdf": secret}, "context_line": secret, "pre_context": [secret]},
             ]}}]}}
    with bind_log_context(request_id="req-123", doc_id="document-123"):
        result = scrub_event(event, {})
    assert secret not in json.dumps(result)
    assert result["tags"] == {"request_id": "req-123", "doc_id": "document-123"}
    assert result["exception"]["values"][0]["stacktrace"]["frames"] == [{"filename": "main.py", "function": "run", "lineno": 42}]


def test_real_sdk_transport_receives_no_request_exception_or_breadcrumb_content():
    envelopes = []
    class Capture(Transport):
        def capture_envelope(self, envelope):
            envelopes.append(envelope)

    previous = sentry_sdk.get_client()
    try:
        configure_sentry(AppConfig(sentry_dsn="https://public@example.test/1"))
        client = sentry_sdk.get_client()
        client.transport.kill()
        client.transport = Capture(client.options)
        secret = "PRIVATE PDF secret-token https://example.test/?signed=abc"
        with sentry_sdk.isolation_scope() as scope, bind_log_context(request_id="job-request"):
            scope.set_extra("prompt", secret)
            scope.set_user({"email": secret})
            sentry_sdk.add_breadcrumb(message=secret)
            try:
                raise ValueError(secret)
            except ValueError:
                logging.getLogger("app.worker").exception("document_job_failed")
        sentry_sdk.flush()
        assert len(envelopes) == 1
        payload = envelopes[0].get_event()
        assert payload["message"] == "document_job_failed"
        assert payload["tags"]["request_id"] == "job-request"
        assert secret not in json.dumps(payload)
        assert not {"request", "user", "extra", "breadcrumbs", "contexts"} & payload.keys()
    finally:
        sentry_sdk.get_client().close()
        sentry_sdk.get_global_scope().set_client(previous)
