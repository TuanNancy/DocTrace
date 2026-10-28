"""Workspace monthly chat quota, document quota and idempotent admission.

Postgres owns the quota decision. One transaction inserts the chat request,
reserves one question and returns the admission, so concurrent requests can
never overshoot a plan limit. Redis document counts provide the per-workspace
document quota; the repository re-checks it inside its WATCH/MULTI create to
close the upload race without a second Postgres transaction.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timezone
from typing import Optional, TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.core.config import AppConfig, get_config
from app.core.errors import api_error
from app.db import DatabaseNotConfigured, session_scope
from app.services.document_locks import lock_document
from app.services.transcripts import ensure_conversation, insert_message

if TYPE_CHECKING:
    from app.services.document_repository import DocumentRepository

logger = logging.getLogger(__name__)

CHAT_METRIC = "chat_questions_month"
DOCUMENT_METRIC = "documents"
CHAT_EXHAUSTED = "Đã hết lượt hỏi trong tháng."
DOCUMENT_EXHAUSTED = "Đã dùng hết số tài liệu của gói hiện tại."
CHAT_STATUSES = ("admitted", "streaming", "completed", "failed", "interrupted")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def period_start(now: Optional[datetime] = None) -> date:
    """UTC month used by usage_counters; quotas reset on the first day."""
    current = (now or utcnow()).astimezone(timezone.utc)
    return current.date().replace(day=1)


def reset_at(now: Optional[datetime] = None) -> datetime:
    current = (now or utcnow()).astimezone(timezone.utc)
    year, month = (
        (current.year + 1, 1) if current.month == 12
        else (current.year, current.month + 1)
    )
    return datetime(year, month, 1, tzinfo=timezone.utc)


def reset_iso(now: Optional[datetime] = None) -> str:
    return reset_at(now).isoformat().replace("+00:00", "Z")


def retry_after_seconds(now: Optional[datetime] = None) -> int:
    current = (now or utcnow()).astimezone(timezone.utc)
    return max(1, math.ceil((reset_at(current) - current).total_seconds()))


def period_utc(now: Optional[datetime] = None) -> datetime:
    start = period_start(now)
    return datetime(start.year, start.month, 1, tzinfo=timezone.utc)


def _uuid(value: str, code: str, message: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        raise api_error(400, code, message) from None


def document_quota_error(limit: int, used: int) -> HTTPException:
    return api_error(
        429, "quota_exceeded", DOCUMENT_EXHAUSTED,
        metric=DOCUMENT_METRIC, limit=limit, used=used,
    )


def duplicate_error(row: dict) -> HTTPException:
    """Reject a repeated client request id without reserving another question."""
    status = row.get("status")
    extra = {"chat_request_id": row.get("chat_request_id")}
    if status == "completed":
        return api_error(
            409, "request_completed", "Yêu cầu này đã hoàn tất.",
            conversation_id=row.get("conversation_id"), **extra,
        )
    if status in ("admitted", "streaming"):
        return api_error(
            409, "request_in_progress", "Yêu cầu này đang được xử lý.", **extra,
        )
    return api_error(
        409, "request_failed",
        "Yêu cầu trước đã kết thúc. Hãy gửi lại với mã yêu cầu mới.",
        retryable=True, **extra,
    )


class QuotaService:
    def __init__(self, config: AppConfig, repository: DocumentRepository | None = None):
        from app.services.document_repository import DocumentRepository

        self.config = config
        self.repository = repository if repository is not None else DocumentRepository(config)

    async def _run(self, action, *args):
        def call():
            with session_scope(self.config) as session:
                return action(session, *args)

        try:
            return await run_in_threadpool(call)
        except HTTPException:
            raise
        except DatabaseNotConfigured as exc:
            raise api_error(503, "quota_unavailable", "Dịch vụ quota chưa được cấu hình.") from exc
        except Exception as exc:
            logger.exception("Quota operation failed")
            raise api_error(503, "quota_unavailable", "Không thể kiểm tra quota. Vui lòng thử lại.") from exc

    @staticmethod
    def _limit(session, plan: str, metric: str) -> int:
        value = session.execute(text(
            """
            SELECT limit_value FROM doctrace.plan_limits
            WHERE plan = :plan AND metric = :metric
            """
        ), {"plan": plan, "metric": metric}).scalar_one_or_none()
        return int(value or 0)

    @staticmethod
    def _existing(session, workspace_id: str, user_id: str, request_id: str) -> dict | None:
        row = session.execute(text(
            """
            SELECT id::text AS chat_request_id, status,
                   conversation_id::text AS conversation_id
            FROM doctrace.chat_requests
            WHERE workspace_id = CAST(:workspace_id AS uuid)
              AND user_id = CAST(:user_id AS uuid)
              AND request_id = CAST(:request_id AS uuid)
            """
        ), {
            "workspace_id": workspace_id, "user_id": user_id, "request_id": request_id,
        }).mappings().first()
        return dict(row) if row else None

    def _admit_chat(self, session, workspace_id: str, user_id: str, request_id: str,
                    doc_id: str, plan: str, query: str = "",
                    index_id: str | None = None) -> dict:
        workspace_id = _uuid(workspace_id, "workspace_invalid", "Workspace không hợp lệ.")
        user_id = _uuid(user_id, "invalid_user", "Người dùng không hợp lệ.")
        request_id = _uuid(request_id, "invalid_request_id", "Mã yêu cầu không hợp lệ.")
        doc_id = _uuid(doc_id, "document_invalid", "Tài liệu không hợp lệ.")

        existing = self._existing(session, workspace_id, user_id, request_id)
        if existing:
            raise duplicate_error(existing)

        lock_document(session, workspace_id, user_id, doc_id)
        document = self.repository.get_sync(workspace_id, user_id, doc_id)
        if (document["status"] != "ready" or not document.get("active_index_id")
                or document.get("delete_requested_at")
                or (index_id is not None and document["active_index_id"] != index_id)):
            raise api_error(409, "document_not_ready", "Tài liệu chưa sẵn sàng để hỏi đáp.")
        index_id = document["active_index_id"]

        inserted = session.execute(text(
            """
            INSERT INTO doctrace.chat_requests
                (request_id, workspace_id, user_id, doc_id, status)
            VALUES
                (CAST(:request_id AS uuid), CAST(:workspace_id AS uuid),
                 CAST(:user_id AS uuid), CAST(:doc_id AS uuid), 'admitted')
            ON CONFLICT (workspace_id, user_id, request_id) DO NOTHING
            RETURNING id::text AS chat_request_id
            """
        ), {
            "request_id": request_id, "workspace_id": workspace_id,
            "user_id": user_id, "doc_id": doc_id,
        }).mappings().first()
        if not inserted:
            # A concurrent request with the same id committed between our
            # fast-path read and this insert. It already owns the reservation.
            existing = self._existing(session, workspace_id, user_id, request_id)
            if existing:
                raise duplicate_error(existing)
            raise api_error(409, "request_in_progress", "Yêu cầu này đang được xử lý.")

        period = period_start()
        session.execute(text(
            """
            INSERT INTO doctrace.usage_counters (workspace_id, period_start, metric, used)
            VALUES (CAST(:workspace_id AS uuid), :period_start, :metric, 0)
            ON CONFLICT (workspace_id, period_start, metric) DO NOTHING
            """
        ), {
            "workspace_id": workspace_id, "period_start": period, "metric": CHAT_METRIC,
        })

        limit = self._limit(session, plan, CHAT_METRIC)
        used = session.execute(text(
            """
            UPDATE doctrace.usage_counters
            SET used = used + 1, updated_at = now()
            WHERE workspace_id = CAST(:workspace_id AS uuid)
              AND period_start = :period_start
              AND metric = :metric
              AND used < :limit
            RETURNING used
            """
        ), {
            "workspace_id": workspace_id, "period_start": period,
            "metric": CHAT_METRIC, "limit": limit,
        }).scalar_one_or_none()
        if used is None:
            current = session.execute(text(
                """
                SELECT used FROM doctrace.usage_counters
                WHERE workspace_id = CAST(:workspace_id AS uuid)
                  AND period_start = :period_start AND metric = :metric
                """
            ), {
                "workspace_id": workspace_id, "period_start": period, "metric": CHAT_METRIC,
            }).scalar_one_or_none()
            retry_after = retry_after_seconds()
            # Raising rolls the transaction back, including the chat_requests
            # row, so the client can retry the same id after upgrading.
            raise api_error(
                429, "quota_exceeded", CHAT_EXHAUSTED,
                metric=CHAT_METRIC, limit=limit, used=int(current or 0),
                reset_at=reset_iso(), retry_after=retry_after,
                headers={"Retry-After": str(retry_after)},
            )

        # The conversation, both messages and the chat request commit together
        # with the quota reservation. A quota denial leaves no transcript row.
        conversation_id = ensure_conversation(session, workspace_id, user_id, doc_id)
        insert_message(
            session, conversation_id, role="user", content=query, status="complete",
        )
        assistant_message_id = insert_message(
            session, conversation_id, role="assistant", sources=[], index_id=index_id,
            status="pending",
        )
        session.execute(text(
            """
            UPDATE doctrace.chat_requests
            SET conversation_id = CAST(:conversation_id AS uuid)
            WHERE id = CAST(:chat_request_id AS uuid)
            """
        ), {
            "conversation_id": conversation_id,
            "chat_request_id": inserted["chat_request_id"],
        })

        return {
            "chat_request_id": inserted["chat_request_id"],
            "request_id": request_id,
            "conversation_id": conversation_id,
            "assistant_message_id": assistant_message_id,
            "used": int(used),
            "limit": limit,
            "reset_at": reset_iso(),
        }

    async def existing_chat(self, workspace_id: str, user_id: str, request_id: str) -> dict | None:
        return await self._run(self._existing, workspace_id, user_id, request_id)

    async def admit_chat(self, workspace_id: str, user_id: str, request_id: str,
                         doc_id: str, plan: str, *, query: str = "",
                         index_id: str | None = None) -> dict:
        return await self._run(
            self._admit_chat, workspace_id, user_id, request_id, doc_id, plan,
            query, index_id,
        )

    def _document_limit(self, session, plan: str) -> int:
        return self._limit(session, plan, DOCUMENT_METRIC)

    async def document_limit(self, plan: str) -> int:
        return await self._run(self._document_limit, plan)

    def _mark_chat(self, session, chat_request_id: str, status: str,
                   error_code: str | None) -> bool:
        if status not in CHAT_STATUSES:
            raise ValueError("Unknown chat request status")
        chat_request_id = _uuid(
            chat_request_id, "invalid_chat_request", "Yêu cầu chat không hợp lệ.",
        )
        if status == "streaming":
            result = session.execute(text(
                """
                UPDATE doctrace.chat_requests
                SET status = 'streaming'
                WHERE id = CAST(:id AS uuid) AND status = 'admitted'
                """
            ), {"id": chat_request_id})
        else:
            result = session.execute(text(
                """
                UPDATE doctrace.chat_requests
                SET status = :status, error_code = :error_code, completed_at = now()
                WHERE id = CAST(:id AS uuid) AND status IN ('admitted', 'streaming')
                """
            ), {"id": chat_request_id, "status": status, "error_code": error_code})
        return bool(result.rowcount)

    async def mark_chat_status(self, chat_request_id: str, status: str,
                               error_code: str | None = None) -> bool:
        return await self._run(self._mark_chat, chat_request_id, status, error_code)

    def _usage(self, session, workspace_id: str, plan: str, user_id: str, role: str) -> dict:
        workspace_id = _uuid(workspace_id, "workspace_invalid", "Workspace không hợp lệ.")
        user_id = _uuid(user_id, "invalid_user", "Người dùng không hợp lệ.")
        period = period_start()
        start = period_utc()
        chat_limit = self._limit(session, plan, CHAT_METRIC)
        document_limit = self._limit(session, plan, DOCUMENT_METRIC)
        chat_used = session.execute(text(
            """
            SELECT used FROM doctrace.usage_counters
            WHERE workspace_id = CAST(:workspace_id AS uuid)
              AND period_start = :period_start AND metric = :metric
            """
        ), {
            "workspace_id": workspace_id, "period_start": period, "metric": CHAT_METRIC,
        }).scalar_one_or_none()

        scope = "" if role == "owner" else " AND user_id = CAST(:user_id AS uuid)"
        params = {"workspace_id": workspace_id, "start": start}
        if role != "owner":
            params["user_id"] = user_id
        chats = session.execute(text(
            f"""
            SELECT user_id::text AS user_id, count(*) AS chat_questions
            FROM doctrace.chat_requests
            WHERE workspace_id = CAST(:workspace_id AS uuid)
              AND created_at >= :start{scope}
            GROUP BY user_id
            """
        ), params).mappings().all()
        costs = session.execute(text(
            f"""
            SELECT user_id::text AS user_id,
                   coalesce(sum(cost_micros), 0)::bigint AS cost_micros,
                   count(*) FILTER (WHERE cost_micros IS NULL) AS cost_unknown_calls
            FROM doctrace.provider_calls
            WHERE workspace_id = CAST(:workspace_id AS uuid)
              AND created_at >= :start AND user_id IS NOT NULL{scope}
            GROUP BY user_id
            """
        ), params).mappings().all()

        by_user: dict[str, dict] = {}
        for row in chats:
            by_user[row["user_id"]] = {
                "user_id": row["user_id"],
                "chat_questions": int(row["chat_questions"]),
                "cost_micros": 0,
                "cost_unknown_calls": 0,
            }
        for row in costs:
            entry = by_user.setdefault(row["user_id"], {
                "user_id": row["user_id"], "chat_questions": 0,
                "cost_micros": 0, "cost_unknown_calls": 0,
            })
            entry["cost_micros"] = int(row["cost_micros"] or 0)
            entry["cost_unknown_calls"] = int(row["cost_unknown_calls"] or 0)

        used = int(chat_used or 0)
        return {
            "workspace_id": workspace_id,
            "plan": plan,
            "period_start": period.isoformat(),
            "reset_at": reset_iso(),
            "chat": {
                "used": used,
                "limit": chat_limit,
                "remaining": max(0, chat_limit - used),
                "metric": CHAT_METRIC,
            },
            "documents": {
                "used": 0,
                "limit": document_limit,
                "remaining": max(0, document_limit),
                "metric": DOCUMENT_METRIC,
            },
            "by_user": sorted(by_user.values(), key=lambda item: item["user_id"]),
        }

    async def usage(self, workspace_id: str, plan: str, user_id: str, role: str) -> dict:
        return await self._run(self._usage, workspace_id, plan, user_id, role)


def get_quota_service() -> QuotaService:
    return QuotaService(get_config())
