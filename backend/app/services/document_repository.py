"""Owner-scoped library and transactional outbox through server-only PostgREST."""
from __future__ import annotations

import logging
from uuid import UUID
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import HTTPException

from app.core.config import AppConfig, get_config

logger = logging.getLogger(__name__)

PUBLIC_FIELDS = (
    "doc_id", "name", "size_bytes", "status", "chunks_count", "warnings", "error", "created_at", "updated_at",
)


def public_document(document: dict) -> dict:
    return {key: document.get(key) for key in PUBLIC_FIELDS}


class DocumentRepository:
    def __init__(self, config: AppConfig):
        self.config = config

    async def request(self, method: str, path: str, *, params=None, body=None):
        if not self.config.supabase_url or not self.config.supabase_service_role_key:
            raise HTTPException(503, "Thư viện chưa được cấu hình trên máy chủ.")
        try:
            async with httpx.AsyncClient(timeout=self.config.upstream_timeout_seconds) as client:
                response = await client.request(
                    method, f"{self.config.supabase_url.rstrip('/')}/rest/v1/{path}",
                    headers={"apikey": self.config.supabase_service_role_key,
                             "Authorization": f"Bearer {self.config.supabase_service_role_key}",
                             "Prefer": "return=representation"}, params=params, json=body,
                )
            if response.is_error:
                code = response.json().get("code")
                if code == "P0002":
                    raise HTTPException(404, "Không tìm thấy tài liệu.")
                if code == "P0001":
                    raise HTTPException(409, "Tài liệu đang được xử lý hoặc không thể thực hiện thao tác này.")
                logger.error("Document database request failed: HTTP %s, code %s", response.status_code, code)
                raise HTTPException(503, "Không thể truy cập thư viện. Kiểm tra cấu hình và migration trên máy chủ.")
            return response.json() if response.content else None
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Document database unavailable: %s", type(exc).__name__)
            raise HTTPException(503, "Không thể kết nối thư viện. Vui lòng thử lại.") from exc

    async def get(self, user_id: str, doc_id: str) -> dict:
        try:
            UUID(doc_id)
        except ValueError:
            raise HTTPException(404, "Không tìm thấy tài liệu.") from None
        rows = await self.request("GET", "documents", params={
            "user_id": f"eq.{user_id}", "doc_id": f"eq.{doc_id}", "status": "neq.deleted", "limit": "1",
        })
        if not rows:
            raise HTTPException(404, "Không tìm thấy tài liệu.")
        return rows[0]

    async def list(self, user_id: str, limit: int, offset: int) -> dict:
        rows = await self.request("GET", "documents", params={
            "user_id": f"eq.{user_id}", "status": "neq.deleted", "order": "created_at.desc,doc_id.desc",
            "limit": str(limit + 1), "offset": str(offset), "select": ",".join(PUBLIC_FIELDS),
        })
        return {"items": rows[:limit], "has_more": len(rows) > limit}

    async def create(self, document: dict) -> dict:
        rows = await self.request("POST", "documents", body=document)
        return rows[0]

    async def upload_failed(self, user_id: str, doc_id: str) -> None:
        await self.request("PATCH", "documents", params={
            "user_id": f"eq.{user_id}", "doc_id": f"eq.{doc_id}", "status": "eq.uploading",
        }, body={"status": "error", "error": "Không thể lưu PDF. Vui lòng tải lại tài liệu."})

    async def queue(self, user_id: str, doc_id: str, kind: str) -> dict:
        return await self.request("POST", "rpc/request_document_operation", body={
            "p_user_id": user_id, "p_doc_id": doc_id, "p_kind": kind,
        })

    async def begin(self, operation_id: str, delivery: int, timeout: int) -> dict | None:
        return await self.request("POST", "rpc/begin_document_attempt", body={
            "p_operation_id": operation_id, "p_delivery": delivery, "p_timeout": timeout,
        })

    async def finish(self, attempt: dict, *, error=None, retryable=False, chunks_count=0, warnings=None) -> bool:
        return await self.request("POST", "rpc/finish_document_attempt", body={
            "p_operation_id": attempt["operation_id"], "p_attempt_id": attempt["attempt_id"],
            "p_error": error, "p_retryable": retryable, "p_chunks_count": chunks_count, "p_warnings": warnings or [],
        })

    async def pending_operations(self):
        # Keyset pagination: live jobs in the first page must not starve later uploads.
        cursor = None
        while True:
            params = {"state": "eq.pending", "order": "operation_id.asc", "limit": "100"}
            if cursor:
                params["operation_id"] = f"gt.{cursor}"
            rows = await self.request("GET", "document_operations", params=params)
            for row in rows:
                yield row
            if len(rows) < 100:
                break
            cursor = rows[-1]["operation_id"]

    async def dispatched(self, operation: dict) -> None:
        await self.request("PATCH", "document_operations", params={
            "operation_id": f"eq.{operation['operation_id']}", "delivery": f"eq.{operation['delivery']}",
            "state": "eq.pending",
        }, body={"dispatched_at": datetime.now(timezone.utc).isoformat()})

    async def recover(self, operation: dict, *, terminal=False) -> bool:
        return await self.request("POST", "rpc/recover_document_operation", body={
            "p_operation_id": operation["operation_id"], "p_delivery": operation["delivery"],
            "p_attempt_id": operation["attempt_id"], "p_terminal": terminal,
        })

    async def recover_uploads(self) -> None:
        await self.request("POST", "rpc/recover_stale_document_uploads", body={})

    async def deletion_blocked(self, doc_id: str) -> bool:
        rows = await self.request("GET", "document_operations", params={
            "doc_id": f"eq.{doc_id}", "kind": "eq.index", "limit": "1", "select": "operation_id",
            "attempt_expires_at": f"gt.{datetime.now(timezone.utc).isoformat()}",
        })
        return bool(rows)

    async def generations(self, doc_id: str) -> list[str]:
        rows = []
        while True:
            page = await self.request("GET", "document_generations", params={
                "doc_id": f"eq.{doc_id}", "select": "generation_id",
                "order": "generation_id.asc", "limit": "1000", "offset": str(len(rows)),
            })
            rows.extend(page)
            if len(page) < 1000:
                break
        return [row["generation_id"] for row in rows]

    async def cleanup_due(self) -> list[dict]:
        rows = []
        cursor = None
        while True:
            params = {"cleanup_after": f"lt.{datetime.now(timezone.utc).isoformat()}",
                      "order": "doc_id.asc", "limit": "100"}
            if cursor:
                params["doc_id"] = f"gt.{cursor}"
            page = await self.request("GET", "documents", params=params)
            rows.extend(page)
            if len(page) < 100:
                return rows
            cursor = page[-1]["doc_id"]

    async def internal_document(self, doc_id: str) -> dict | None:
        """Worker-only read, including tombstones; ownership comes from this row."""
        rows = await self.request("GET", "documents", params={"doc_id": f"eq.{doc_id}", "limit": "1"})
        return rows[0] if rows else None

    async def cleanup_candidates(self, doc_id: str) -> list[str]:
        return await self.request("POST", "rpc/document_cleanup_candidates", body={"p_doc_id": doc_id})

    async def cleanup_finished(self, doc_id: str, expected: str) -> None:
        await self.request("PATCH", "documents", params={"doc_id": f"eq.{doc_id}", "cleanup_after": f"eq.{expected}"},
                            body={"cleanup_after": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})


def get_document_repository() -> DocumentRepository:
    return DocumentRepository(get_config())
