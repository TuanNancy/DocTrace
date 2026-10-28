"""Workspace tenancy: membership checks, roles, plans and lifecycle.

Postgres is the control plane. Documents stay private to their owner in Redis.
The header selects a workspace; every method re-checks active membership.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.core.config import AppConfig, get_config
from app.core.errors import api_error
from app.db import DatabaseNotConfigured, session_scope

if TYPE_CHECKING:
    from app.services.document_repository import DocumentRepository

logger = logging.getLogger(__name__)

PERSONAL_NAME = "Cá nhân"


@dataclass(frozen=True)
class WorkspaceContext:
    workspace_id: str
    user_id: str
    role: str
    plan: str
    kind: str
    name: str


def _uuid(value: str, code: str = "invalid_uuid") -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        raise api_error(400, code, "ID không hợp lệ.") from None


def _workspace(row) -> dict:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "kind": row["kind"],
        "plan": row["plan"],
        "role": row["role"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


def _member(row) -> dict:
    return {
        "user_id": str(row["user_id"]),
        "role": row["role"],
        "status": row["status"],
        "email": row.get("email"),
        "display_name": row.get("display_name"),
        "joined_at": row["joined_at"].isoformat() if row.get("joined_at") else None,
    }


class WorkspaceService:
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
            raise api_error(503, "workspace_unavailable", "Workspace service chưa được cấu hình.") from exc
        except Exception as exc:
            logger.exception("workspace_operation_failed")
            raise api_error(503, "workspace_unavailable",
                            "Không thể truy cập workspace. Vui lòng thử lại.") from exc

    def _ensure_personal(self, session, user_id: str) -> None:
        """Demo shortcut: a personal workspace is keyed by the owner's user id."""
        user_id = _uuid(user_id)
        session.execute(text(
            """
            INSERT INTO doctrace.workspaces
                (id, name, kind, plan, created_by, personal_owner_user_id)
            VALUES (:uid, :name, 'personal', 'free', :uid, :uid)
            ON CONFLICT (id) DO NOTHING
            """
        ), {"uid": user_id, "name": PERSONAL_NAME})
        session.execute(text(
            """
            INSERT INTO doctrace.workspace_members (workspace_id, user_id, role, status)
            VALUES (:uid, :uid, 'owner', 'active')
            ON CONFLICT (workspace_id, user_id) DO NOTHING
            """
        ), {"uid": user_id})

    def _list_for_user(self, session, user_id: str) -> list[dict]:
        self._ensure_personal(session, user_id)
        rows = session.execute(text(
            """
            SELECT w.id, w.name, w.kind, w.plan, w.status, w.created_at, m.role
            FROM doctrace.workspace_members m
            JOIN doctrace.workspaces w ON w.id = m.workspace_id
            WHERE m.user_id = :uid AND m.status = 'active'
            ORDER BY (w.kind = 'personal') DESC, (w.status = 'archived'), w.created_at
            """
        ), {"uid": user_id}).mappings().all()
        return [_workspace(row) for row in rows]

    async def list_for_user(self, user_id: str) -> list[dict]:
        return await self._run(self._list_for_user, user_id)

    def _resolve(self, session, user_id: str, workspace_id: str,
                 *, lock_member: bool = False) -> WorkspaceContext:
        workspace_id = _uuid(workspace_id, "workspace_invalid")
        user_id = _uuid(user_id)
        if workspace_id == user_id:
            self._ensure_personal(session, user_id)
        row = session.execute(text(
            """
            SELECT w.id, w.name, w.kind, w.plan, w.status, m.role
            FROM doctrace.workspaces w
            JOIN doctrace.workspace_members m ON m.workspace_id = w.id
            WHERE w.id = :wid AND m.user_id = :uid
              AND m.status = 'active' AND w.status = 'active'
            """ + (" FOR SHARE OF m" if lock_member else "")
        ), {"wid": workspace_id, "uid": user_id}).mappings().first()
        if not row:
            raise api_error(404, "workspace_not_found", "Không tìm thấy workspace.")
        return WorkspaceContext(
            workspace_id=str(row["id"]), user_id=user_id, role=row["role"],
            plan=row["plan"], kind=row["kind"], name=row["name"],
        )

    async def resolve(self, user_id: str, workspace_id: str) -> WorkspaceContext:
        return await self._run(self._resolve, user_id, workspace_id)

    def _lock_workspace(self, session, workspace_id: str) -> None:
        """Lock order is always workspace, then membership; archive updates w.

        FOR SHARE conflicts with a status UPDATE, unlike FOR KEY SHARE. Uploads
        can still commit concurrently. Storage/provider calls stay outside these
        locks; only the bounded Redis catalog transaction runs while held.
        """
        row = session.execute(text(
            "SELECT id FROM doctrace.workspaces WHERE id = :wid AND status = 'active' FOR SHARE"
        ), {"wid": _uuid(workspace_id, "workspace_invalid")}).first()
        if not row:
            raise api_error(404, "workspace_not_found", "Không tìm thấy workspace.")

    def _create_document(self, session, document: dict, repository: DocumentRepository,
                         limit: int) -> dict:
        self._lock_workspace(session, document["workspace_id"])
        self._resolve(session, document["owner_user_id"], document["workspace_id"], lock_member=True)
        return repository.create_sync(document, limit=limit)

    async def create_document(self, document: dict, repository: DocumentRepository,
                              *, limit: int) -> dict:
        """Recheck membership and hold it through catalog commit, after PDF retention."""
        return await self._run(self._create_document, document, repository, limit)

    def _owned_workspace(self, session, user_id: str, workspace_id: str,
                         *, allow_archived: bool = False) -> dict:
        workspace_id = _uuid(workspace_id, "workspace_invalid")
        row = session.execute(text(
            """
            SELECT w.id, w.name, w.kind, w.plan, w.status, w.created_at, m.role
            FROM doctrace.workspaces w
            JOIN doctrace.workspace_members m ON m.workspace_id = w.id
            WHERE w.id = :wid AND m.user_id = :uid
              AND m.status = 'active' AND m.role = 'owner'
              AND (:allow_archived OR w.status = 'active')
            """
        ), {"wid": workspace_id, "uid": user_id, "allow_archived": allow_archived}).mappings().first()
        if not row:
            raise api_error(404, "workspace_not_found", "Không tìm thấy workspace.")
        return _workspace(row)

    def _create(self, session, user_id: str, name: str) -> dict:
        user_id = _uuid(user_id)
        name = name.strip()
        if not name:
            raise api_error(400, "workspace_name_required", "Tên workspace không được để trống.")
        if len(name) > 80:
            raise api_error(400, "workspace_name_too_long", "Tên workspace tối đa 80 ký tự.")
        self._ensure_personal(session, user_id)
        # Serialize two create requests for the same owner.
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                        {"key": f"workspace-create:{user_id}"})
        owned = session.execute(text(
            """
            SELECT count(*) FROM doctrace.workspaces w
            JOIN doctrace.workspace_members m ON m.workspace_id = w.id
            WHERE m.user_id = :uid AND m.role = 'owner' AND m.status = 'active'
              AND w.status = 'active'
            """
        ), {"uid": user_id}).scalar_one()
        limit = session.execute(text(
            """
            SELECT coalesce(max(l.limit_value), 1)
            FROM doctrace.plan_limits l
            WHERE l.metric = 'workspaces' AND l.plan IN (
                SELECT DISTINCT w.plan FROM doctrace.workspaces w
                JOIN doctrace.workspace_members m ON m.workspace_id = w.id
                WHERE m.user_id = :uid AND m.role = 'owner' AND m.status = 'active'
                  AND w.status = 'active'
            )
            """
        ), {"uid": user_id}).scalar_one()
        if owned >= limit:
            raise api_error(403, "plan_required", "Bạn đã dùng hết số workspace của gói hiện tại.",
                            metric="workspaces", limit=limit)
        row = session.execute(text(
            """
            INSERT INTO doctrace.workspaces (name, kind, plan, created_by)
            VALUES (:name, 'team', 'free', :uid)
            RETURNING id, name, kind, plan, status, created_at
            """
        ), {"name": name, "uid": user_id}).mappings().one()
        session.execute(text(
            """
            INSERT INTO doctrace.workspace_members (workspace_id, user_id, role, status)
            VALUES (:wid, :uid, 'owner', 'active')
            """
        ), {"wid": row["id"], "uid": user_id})
        return {**_workspace({**row, "role": "owner"})}

    async def create(self, user_id: str, name: str) -> dict:
        return await self._run(self._create, user_id, name)

    def _members(self, session, user_id: str, workspace_id: str) -> list[dict]:
        self._owned_workspace(session, user_id, workspace_id)
        rows = session.execute(text(
            """
            SELECT m.user_id, m.role, m.status, m.joined_at, p.email, p.display_name
            FROM doctrace.workspace_members m
            LEFT JOIN doctrace.profiles p ON p.user_id = m.user_id
            WHERE m.workspace_id = :wid AND m.status <> 'removed'
            ORDER BY (m.role = 'owner') DESC, m.joined_at
            """
        ), {"wid": _uuid(workspace_id, "workspace_invalid")}).mappings().all()
        return [_member(row) for row in rows]

    async def members(self, user_id: str, workspace_id: str) -> list[dict]:
        return await self._run(self._members, user_id, workspace_id)

    def _assert_owner(self, session, user_id: str, workspace_id: str) -> None:
        self._owned_workspace(session, user_id, workspace_id)

    async def assert_owner(self, user_id: str, workspace_id: str) -> None:
        await self._run(self._assert_owner, user_id, workspace_id)

    def _add_member(self, session, user_id: str, workspace_id: str, member_id: str) -> dict:
        self._lock_workspace(session, workspace_id)
        self._owned_workspace(session, user_id, workspace_id)
        workspace_id = _uuid(workspace_id, "workspace_invalid")
        member_id = _uuid(member_id, "member_invalid")
        # Authorize first: membership management must not become an Auth-user
        # lookup for strangers. Check on every add, including reactivation and
        # duplicate adds; a stale profile/membership is not proof of an account.
        exists = session.execute(text(
            "SELECT doctrace.auth_user_exists(CAST(:member AS uuid))"
        ), {"member": member_id}).scalar()
        if not exists:
            raise api_error(404, "member_user_not_found", "Không tìm thấy tài khoản người dùng.")
        row = session.execute(text(
            """
            INSERT INTO doctrace.workspace_members (workspace_id, user_id, role, status)
            VALUES (:wid, :member, 'member', 'active')
            ON CONFLICT (workspace_id, user_id) DO UPDATE
            SET role = 'member', status = 'active', removed_at = NULL, joined_at = now()
            WHERE doctrace.workspace_members.status <> 'active'
            RETURNING user_id, role, status, joined_at
            """
        ), {"wid": workspace_id, "member": member_id}).mappings().first()
        if not row:
            row = session.execute(text(
                """
                SELECT user_id, role, status, joined_at
                FROM doctrace.workspace_members
                WHERE workspace_id = :wid AND user_id = :member
                """
            ), {"wid": workspace_id, "member": member_id}).mappings().one()
        return _member(row)

    async def add_member(self, user_id: str, workspace_id: str, member_id: str) -> dict:
        return await self._run(self._add_member, user_id, workspace_id, member_id)

    def _remove_member(self, session, user_id: str, workspace_id: str, member_id: str,
                       repository: DocumentRepository) -> dict:
        self._lock_workspace(session, workspace_id)
        self._owned_workspace(session, user_id, workspace_id)
        workspace_id = _uuid(workspace_id, "workspace_invalid")
        member_id = _uuid(member_id, "member_invalid")
        if member_id == _uuid(user_id):
            raise api_error(409, "cannot_remove_owner", "Owner không thể tự rời workspace.")
        row = session.execute(text(
            """
            SELECT role, status FROM doctrace.workspace_members
            WHERE workspace_id = :wid AND user_id = :member
            FOR UPDATE
            """
        ), {"wid": workspace_id, "member": member_id}).mappings().first()
        if not row or row["status"] == "removed":
            raise api_error(404, "member_not_found", "Không tìm thấy thành viên.")
        if row["role"] == "owner":
            raise api_error(409, "cannot_remove_owner", "Không thể xóa owner của workspace.")
        session.execute(text(
            "UPDATE doctrace.workspace_members SET status = 'removing' "
            "WHERE workspace_id = :wid AND user_id = :member"
        ), {"wid": workspace_id, "member": member_id})
        # Read only after taking the lock shared by upload commit. Raising below
        # rolls 'removing' back to active, including on a Redis timeout/error.
        document_count = repository.count_workspace_sync(workspace_id, member_id)
        if document_count > 0:
            raise api_error(
                409, "member_has_documents",
                "Thành viên còn tài liệu chưa xóa trong workspace.",
                document_count=document_count,
            )
        session.execute(text(
            """
            UPDATE doctrace.workspace_members
            SET status = 'removed', removed_at = now()
            WHERE workspace_id = :wid AND user_id = :member
            """
        ), {"wid": workspace_id, "member": member_id})
        return {"user_id": member_id, "status": "removed"}

    async def remove_member(self, user_id: str, workspace_id: str, member_id: str,
                            repository: DocumentRepository) -> dict:
        return await self._run(self._remove_member, user_id, workspace_id, member_id, repository)

    def _archive(self, session, user_id: str, workspace_id: str) -> dict:
        self._owned_workspace(session, user_id, workspace_id)
        row = session.execute(text(
            """
            UPDATE doctrace.workspaces
            SET status = 'archived', archived_at = now(), archived_by = :uid, updated_at = now()
            WHERE id = :wid AND status = 'active'
            RETURNING id, name, kind, plan, status, created_at
            """
        ), {"wid": _uuid(workspace_id, "workspace_invalid"), "uid": _uuid(user_id)}).mappings().one()
        return _workspace({**row, "role": "owner"})

    async def archive(self, user_id: str, workspace_id: str) -> dict:
        return await self._run(self._archive, user_id, workspace_id)

    def _restore(self, session, user_id: str, workspace_id: str) -> dict:
        admin = session.execute(text(
            "SELECT 1 FROM doctrace.platform_admins WHERE user_id = :uid"
        ), {"uid": _uuid(user_id)}).first()
        if not admin:
            raise api_error(403, "admin_required", "Chỉ platform admin được khôi phục workspace.")
        row = session.execute(text(
            """
            UPDATE doctrace.workspaces
            SET status = 'active', archived_at = NULL, archived_by = NULL, updated_at = now()
            WHERE id = :wid AND status = 'archived'
            RETURNING id, name, kind, plan, status, created_at, created_by
            """
        ), {"wid": _uuid(workspace_id, "workspace_invalid")}).mappings().first()
        if not row:
            raise api_error(404, "workspace_not_found", "Không tìm thấy workspace đã archive.")
        return _workspace({**row, "role": "owner"})

    async def restore(self, user_id: str, workspace_id: str) -> dict:
        return await self._run(self._restore, user_id, workspace_id)


def get_workspace_service() -> WorkspaceService:
    return WorkspaceService(get_config())
