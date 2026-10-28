"""Private chat transcripts and their retention lifecycle.

A conversation belongs to exactly one workspace, user and document. The
``conversations`` and ``messages`` tables are part of the P0 control plane;
this service adds the admission helpers (used by the quota transaction),
owner-scoped reads, streaming finalization and document-deletion retention.

Transcript queries always filter both workspace and user. Workspace owners
never read a member's transcript, even though they can see aggregate usage.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.core.config import AppConfig, get_config
from app.core.errors import api_error
from app.db import DatabaseNotConfigured, session_scope
from app.services.document_locks import lock_document

if TYPE_CHECKING:
    from app.services.document_repository import DocumentRepository

logger = logging.getLogger(__name__)

TRANSCRIPT_DELETE_MODES = ("retain_30d", "cascade")
MESSAGE_STATUSES = ("pending", "streaming", "complete", "interrupted", "error")


def _uuid(value: str, code: str, message: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        raise api_error(400, code, message) from None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def ensure_conversation(session, workspace_id: str, user_id: str, doc_id: str) -> str:
    """Return the active conversation, creating it when this is the first turn.

    The partial unique index ``ux_conversations_active_document`` makes the
    insert safe under concurrent admissions. ``DO UPDATE`` returns the existing
    row, so two turns cannot create duplicate conversations.
    """
    row = session.execute(text(
        """
        INSERT INTO doctrace.conversations
            (workspace_id, user_id, doc_id, created_at, updated_at)
        VALUES
            (CAST(:workspace_id AS uuid), CAST(:user_id AS uuid),
             CAST(:doc_id AS uuid), clock_timestamp(), clock_timestamp())
        ON CONFLICT (workspace_id, user_id, doc_id)
            WHERE document_deleted_at IS NULL AND purge_after IS NULL
        DO UPDATE SET updated_at = clock_timestamp()
        RETURNING id::text AS id
        """
    ), {
        "workspace_id": workspace_id, "user_id": user_id, "doc_id": doc_id,
    }).mappings().first()
    if not row:
        raise api_error(409, "conversation_conflict", "Không thể mở hội thoại mới.")
    return row["id"]


def insert_message(
    session,
    conversation_id: str,
    *,
    role: str,
    content: str = "",
    sources: Optional[list] = None,
    index_id: str | None = None,
    status: str,
) -> str:
    """Insert one ordered message. ``clock_timestamp`` keeps user/assistant pairs ordered."""
    if role not in ("user", "assistant"):
        raise ValueError("Unknown message role")
    if status not in MESSAGE_STATUSES:
        raise ValueError("Unknown message status")
    row = session.execute(text(
        """
        INSERT INTO doctrace.messages
            (conversation_id, role, content, sources, index_id, status,
             created_at, updated_at)
        VALUES
            (CAST(:conversation_id AS uuid), :role, :content,
             CAST(:sources AS jsonb), CAST(:index_id AS uuid), :status,
             clock_timestamp(), clock_timestamp())
        RETURNING id::text AS id
        """
    ), {
        "conversation_id": conversation_id, "role": role, "content": content,
        "sources": json.dumps(sources or []), "index_id": index_id, "status": status,
    }).mappings().first()
    if not row:
        raise api_error(409, "message_conflict", "Không thể lưu tin nhắn.")
    return row["id"]


def stale_sources(conversation: dict, active_index_id: str | None) -> dict:
    """Mark citations from another generation (or a non-ready document) stale.

    Never fetch an old chunk id from the new generation: the client disables
    opening any source marked here.
    """
    current = str(active_index_id) if active_index_id else None
    for message in conversation.get("messages", []):
        if message.get("role") != "assistant":
            continue
        message_index = message.get("index_id")
        stale = current is None or not message_index or str(message_index) != current
        message["stale"] = stale
        for source in message.get("sources") or []:
            source["stale"] = stale
    return conversation


class TranscriptService:
    def __init__(self, config: AppConfig):
        self.config = config

    async def _run(self, action, *args):
        def call():
            with session_scope(self.config) as session:
                return action(session, *args)

        try:
            return await run_in_threadpool(call)
        except HTTPException:
            raise
        except DatabaseNotConfigured as exc:
            raise api_error(503, "transcript_unavailable", "Dịch vụ hội thoại chưa được cấu hình.") from exc
        except Exception as exc:
            logger.exception("transcript_operation_failed")
            raise api_error(503, "transcript_unavailable", "Không thể truy cập hội thoại. Vui lòng thử lại.") from exc

    def _list(self, session, workspace_id: str, user_id: str, doc_id: str | None,
              limit: int) -> dict:
        workspace_id = _uuid(workspace_id, "workspace_invalid", "Workspace không hợp lệ.")
        user_id = _uuid(user_id, "invalid_user", "Người dùng không hợp lệ.")
        doc_filter = ""
        params = {
            "workspace_id": workspace_id, "user_id": user_id,
            "limit": max(1, min(int(limit), 50)),
        }
        if doc_id:
            params["doc_id"] = _uuid(doc_id, "document_invalid", "Tài liệu không hợp lệ.")
            doc_filter = " AND c.doc_id = CAST(:doc_id AS uuid)"
        rows = session.execute(text(
            f"""
            SELECT c.id::text AS id, c.doc_id::text AS doc_id,
                   c.created_at, c.updated_at,
                   (SELECT count(*) FROM doctrace.messages m
                    WHERE m.conversation_id = c.id) AS message_count
            FROM doctrace.conversations c
            WHERE c.workspace_id = CAST(:workspace_id AS uuid)
              AND c.user_id = CAST(:user_id AS uuid)
              AND c.document_deleted_at IS NULL
              AND c.purge_after IS NULL{doc_filter}
            ORDER BY c.updated_at DESC, c.created_at DESC
            LIMIT :limit
            """
        ), params).mappings().all()
        return {
            "items": [{
                "id": row["id"], "doc_id": row["doc_id"],
                "created_at": _iso(row["created_at"]),
                "updated_at": _iso(row["updated_at"]),
                "message_count": int(row["message_count"]),
            } for row in rows],
        }

    async def list(self, workspace_id: str, user_id: str, doc_id: str | None = None,
                   limit: int = 20) -> dict:
        return await self._run(self._list, workspace_id, user_id, doc_id, limit)

    def _get(self, session, workspace_id: str, user_id: str,
             conversation_id: str) -> dict | None:
        workspace_id = _uuid(workspace_id, "workspace_invalid", "Workspace không hợp lệ.")
        user_id = _uuid(user_id, "invalid_user", "Người dùng không hợp lệ.")
        conversation_id = _uuid(
            conversation_id, "conversation_invalid", "Hội thoại không hợp lệ.",
        )
        row = session.execute(text(
            """
            SELECT id::text AS id, workspace_id::text AS workspace_id,
                   doc_id::text AS doc_id, created_at, updated_at
            FROM doctrace.conversations
            WHERE id = CAST(:id AS uuid)
              AND workspace_id = CAST(:workspace_id AS uuid)
              AND user_id = CAST(:user_id AS uuid)
              AND document_deleted_at IS NULL
              AND purge_after IS NULL
            """
        ), {
            "id": conversation_id, "workspace_id": workspace_id, "user_id": user_id,
        }).mappings().first()
        if not row:
            return None
        messages = session.execute(text(
            """
            SELECT id::text AS id, role, content, sources,
                   index_id::text AS index_id, status, created_at, updated_at
            FROM doctrace.messages
            WHERE conversation_id = CAST(:id AS uuid)
            ORDER BY created_at, id
            """
        ), {"id": conversation_id}).mappings().all()
        return {
            "id": row["id"],
            "workspace_id": row["workspace_id"],
            "doc_id": row["doc_id"],
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
            "messages": [{
                "id": message["id"],
                "role": message["role"],
                "content": message["content"],
                "sources": list(message["sources"] or []),
                "index_id": message["index_id"],
                "status": message["status"],
                "created_at": _iso(message["created_at"]),
                "updated_at": _iso(message["updated_at"]),
            } for message in messages],
        }

    async def get(self, workspace_id: str, user_id: str,
                  conversation_id: str) -> dict | None:
        return await self._run(self._get, workspace_id, user_id, conversation_id)

    def _delete(self, session, workspace_id: str, user_id: str,
                conversation_id: str) -> bool:
        workspace_id = _uuid(workspace_id, "workspace_invalid", "Workspace không hợp lệ.")
        user_id = _uuid(user_id, "invalid_user", "Người dùng không hợp lệ.")
        conversation_id = _uuid(
            conversation_id, "conversation_invalid", "Hội thoại không hợp lệ.",
        )
        # For the demo a user deleting a conversation removes the content
        # immediately; messages cascade. Hidden document transcripts use the
        # separate document retention path below.
        doc_id = session.execute(text(
            "SELECT doc_id::text FROM doctrace.conversations WHERE id = CAST(:id AS uuid) "
            "AND workspace_id = CAST(:wid AS uuid) AND user_id = CAST(:uid AS uuid)"
        ), {"id": conversation_id, "wid": workspace_id, "uid": user_id}).scalar_one_or_none()
        if not doc_id:
            return False
        lock_document(session, workspace_id, user_id, doc_id)
        result = session.execute(text(
            """
            DELETE FROM doctrace.conversations
            WHERE id = CAST(:id AS uuid)
              AND workspace_id = CAST(:workspace_id AS uuid)
              AND user_id = CAST(:user_id AS uuid)
              AND document_deleted_at IS NULL
              AND purge_after IS NULL
            """
        ), {
            "id": conversation_id, "workspace_id": workspace_id, "user_id": user_id,
        })
        return bool(result.rowcount)

    async def delete(self, workspace_id: str, user_id: str,
                     conversation_id: str) -> bool:
        return await self._run(self._delete, workspace_id, user_id, conversation_id)

    def _mark_streaming(self, session, assistant_message_id: str) -> bool:
        assistant_message_id = _uuid(
            assistant_message_id, "message_invalid", "Tin nhắn không hợp lệ.",
        )
        result = session.execute(text(
            """
            UPDATE doctrace.messages
            SET status = 'streaming', updated_at = now()
            WHERE id = CAST(:id AS uuid) AND status = 'pending'
            """
        ), {"id": assistant_message_id})
        return bool(result.rowcount)

    async def mark_streaming(self, assistant_message_id: str) -> bool:
        return await self._run(self._mark_streaming, assistant_message_id)

    def _finalize_message(self, session, assistant_message_id: str, status: str,
                          content: str, sources: list, index_id: str | None) -> bool:
        if status not in MESSAGE_STATUSES:
            raise ValueError("Unknown message status")
        assistant_message_id = _uuid(
            assistant_message_id, "message_invalid", "Tin nhắn không hợp lệ.",
        )
        scope = session.execute(text(
            "SELECT c.workspace_id::text, c.user_id::text, c.doc_id::text "
            "FROM doctrace.conversations c JOIN doctrace.messages m ON m.conversation_id = c.id "
            "WHERE m.id = CAST(:id AS uuid)"
        ), {"id": assistant_message_id}).first()
        if not scope:
            return False
        # Take the document fence before message/conversation row locks, matching
        # admission and cascading deletion so finalization cannot deadlock them.
        lock_document(session, *scope)
        result = session.execute(text(
            """
            UPDATE doctrace.messages
            SET content = :content, sources = CAST(:sources AS jsonb),
                index_id = COALESCE(CAST(:index_id AS uuid), index_id),
                status = :status, updated_at = now()
            WHERE id = CAST(:id AS uuid)
              AND status IN ('pending', 'streaming')
              AND EXISTS (
                  SELECT 1 FROM doctrace.conversations c
                  WHERE c.id = doctrace.messages.conversation_id
                    AND c.document_deleted_at IS NULL AND c.purge_after IS NULL
              )
            """
        ), {
            "id": assistant_message_id, "status": status, "content": content,
            "sources": json.dumps(sources or []), "index_id": index_id,
        })
        if result.rowcount:
            session.execute(text(
                """
                UPDATE doctrace.conversations
                SET updated_at = now()
                WHERE id = (SELECT conversation_id FROM doctrace.messages
                            WHERE id = CAST(:id AS uuid))
                """
            ), {"id": assistant_message_id})
        return bool(result.rowcount)

    async def finalize_message(self, assistant_message_id: str, status: str,
                               content: str, sources: list, index_id: str | None = None) -> bool:
        return await self._run(
            self._finalize_message, assistant_message_id, status, content, sources, index_id,
        )

    def _hide_for_document(self, session, workspace_id: str, user_id: str, doc_id: str,
                           mode: str, retention_days: int, deleted_at: str | None = None) -> int:
        workspace_id = _uuid(workspace_id, "workspace_invalid", "Workspace không hợp lệ.")
        user_id = _uuid(user_id, "invalid_user", "Người dùng không hợp lệ.")
        doc_id = _uuid(doc_id, "document_invalid", "Tài liệu không hợp lệ.")
        if mode not in TRANSCRIPT_DELETE_MODES:
            raise ValueError("Unknown transcript delete mode")
        lock_document(session, workspace_id, user_id, doc_id)
        if mode == "cascade":
            result = session.execute(text(
                """
                DELETE FROM doctrace.conversations
                WHERE workspace_id = CAST(:workspace_id AS uuid)
                  AND user_id = CAST(:user_id AS uuid)
                  AND doc_id = CAST(:doc_id AS uuid)
                  AND document_deleted_at IS NULL
                  AND purge_after IS NULL
                """
            ), {
                "workspace_id": workspace_id, "user_id": user_id, "doc_id": doc_id,
            })
        else:
            result = session.execute(text(
                """
                UPDATE doctrace.conversations
                SET document_deleted_at = COALESCE(CAST(:deleted_at AS timestamptz), now()),
                    purge_after = COALESCE(CAST(:deleted_at AS timestamptz), now())
                                  + make_interval(days => :retention_days),
                    updated_at = now()
                WHERE workspace_id = CAST(:workspace_id AS uuid)
                  AND user_id = CAST(:user_id AS uuid)
                  AND doc_id = CAST(:doc_id AS uuid)
                  AND document_deleted_at IS NULL
                  AND purge_after IS NULL
                """
            ), {
                "workspace_id": workspace_id, "user_id": user_id, "doc_id": doc_id,
                "retention_days": retention_days, "deleted_at": deleted_at,
            })
        return int(result.rowcount or 0)

    async def hide_for_document(self, workspace_id: str, user_id: str, doc_id: str,
                                *, deleted_at: str | None = None) -> int:
        return await self._run(
            self._hide_for_document, workspace_id, user_id, doc_id,
            self.config.transcript_delete_mode, self.config.transcript_retention_days, deleted_at,
        )

    def _queue_document_deletion(self, session, workspace_id: str, user_id: str,
                                  doc_id: str, repository: DocumentRepository) -> dict:
        from app.services.workspaces import WorkspaceService

        WorkspaceService(self.config)._lock_workspace(session, workspace_id)
        lock_document(session, workspace_id, user_id, doc_id)
        # Redis validates ownership/live jobs and commits deletion intent first.
        # A rejection leaves content untouched; a lost SQL commit is recovered by
        # the worker before cleanup. Reads also check Redis, closing that window.
        document = repository.queue_sync(workspace_id, user_id, doc_id, "delete")
        self._hide_for_document(
            session, workspace_id, user_id, doc_id,
            self.config.transcript_delete_mode, self.config.transcript_retention_days,
            document.get("delete_requested_at"),
        )
        return document

    async def queue_document_deletion(self, workspace_id: str, user_id: str,
                                      doc_id: str, repository: DocumentRepository) -> dict:
        return await self._run(
            self._queue_document_deletion, workspace_id, user_id, doc_id, repository,
        )

    def _purge_expired(self, session) -> int:
        result = session.execute(text(
            """
            DELETE FROM doctrace.conversations
            WHERE purge_after IS NOT NULL AND purge_after < now()
            """
        ))
        return int(result.rowcount or 0)

    async def purge_expired(self) -> int:
        return await self._run(self._purge_expired)


def purge_expired_transcripts(config: AppConfig | None = None) -> int:
    """Daily retention entry point; cost rows in provider_calls are untouched."""
    config = config or get_config()
    with session_scope(config) as session:
        result = session.execute(text(
            """
            DELETE FROM doctrace.conversations
            WHERE purge_after IS NOT NULL AND purge_after < now()
            """
        ))
        return int(result.rowcount or 0)


def get_transcript_service() -> TranscriptService:
    return TranscriptService(get_config())
