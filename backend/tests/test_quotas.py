"""Monthly quota helpers and structured admission errors (no Postgres needed)."""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.core.config import AppConfig
from app.services import quotas


def test_monthly_period_uses_utc_calendar_month():
    assert quotas.period_start(datetime(2026, 10, 26, 23, 59, tzinfo=timezone.utc)) == (
        datetime(2026, 10, 1).date()
    )
    assert quotas.reset_iso(datetime(2026, 10, 26, 23, 59, tzinfo=timezone.utc)) == (
        "2026-11-01T00:00:00Z"
    )
    assert quotas.retry_after_seconds(
        datetime(2026, 10, 26, 23, 59, tzinfo=timezone.utc)
    ) == 5 * 86400 + 60


def test_december_resets_in_the_next_year():
    now = datetime(2026, 12, 31, 12, 0, tzinfo=timezone.utc)
    assert quotas.reset_at(now) == datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert quotas.period_start(now).isoformat() == "2026-12-01"


@pytest.mark.parametrize("status, code", [
    ("completed", "request_completed"),
    ("admitted", "request_in_progress"),
    ("streaming", "request_in_progress"),
    ("failed", "request_failed"),
    ("interrupted", "request_failed"),
])
def test_duplicate_requests_never_reserve_another_question(status, code):
    error = quotas.duplicate_error({
        "status": status, "chat_request_id": "request-row", "conversation_id": "conversation",
    })
    assert error.status_code == 409
    assert error.detail["code"] == code
    assert error.detail["chat_request_id"] == "request-row"
    if status == "completed":
        assert error.detail["conversation_id"] == "conversation"
    if status in ("failed", "interrupted"):
        assert error.detail["retryable"] is True


def test_chat_quota_error_exposes_limit_usage_and_reset():
    error = quotas.duplicate_error({"status": "failed"})
    assert error.detail["message"]

    document = quotas.document_quota_error(5, 5)
    assert document.status_code == 429
    assert document.detail == {
        "code": "quota_exceeded",
        "message": quotas.DOCUMENT_EXHAUSTED,
        "metric": "documents",
        "limit": 5,
        "used": 5,
    }


async def test_quota_service_is_unavailable_without_database():
    service = quotas.QuotaService(AppConfig(database_url=None))
    with pytest.raises(HTTPException) as caught:
        await service.document_limit("free")
    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "quota_unavailable"
