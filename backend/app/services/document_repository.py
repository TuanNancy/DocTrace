"""Durable library and job queue through Supabase PostgREST (server credentials only)."""
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
        return await self.request("POST", "rpc/queue_document_job", body={
            "p_user_id": user_id, "p_doc_id": doc_id, "p_kind": kind,
        })

    async def claim(self) -> dict | None:
        return await self.request("POST", "rpc/claim_document_job", body={
            "p_lease_seconds": self.config.document_job_lease_seconds,
        })

    async def heartbeat(self, job: dict) -> bool:
        return await self.request("POST", "rpc/heartbeat_document_job", body={
            "p_job_id": job["job_id"], "p_token": job["lease_token"],
            "p_lease_seconds": self.config.document_job_lease_seconds,
        })

    async def finish(self, job: dict, *, error=None, chunks_count=0, warnings=None) -> bool:
        return await self.request("POST", "rpc/finish_document_job", body={
            "p_job_id": job["job_id"], "p_token": job["lease_token"], "p_error": error,
            "p_chunks_count": chunks_count, "p_warnings": warnings or [],
        })

    async def generations(self, doc_id: str) -> list[str]:
        rows = []
        while True:
            page = await self.request("GET", "document_jobs", params={
                "doc_id": f"eq.{doc_id}", "select": "generations", "kind": "eq.index",
                "order": "created_at.asc,job_id.asc", "limit": "1000", "offset": str(len(rows)),
            })
            rows.extend(page)
            if len(page) < 1000:
                break
        return list({generation for row in rows for generation in row["generations"]})

    async def tombstones_due(self) -> list[dict]:
        return await self.request("GET", "documents", params={
            "status": "eq.deleted", "cleanup_after": f"lt.{datetime.now(timezone.utc).isoformat()}",
            "order": "cleanup_after.asc", "limit": "20",
        })

    async def tombstone_cleaned(self, doc_id: str) -> None:
        await self.request("PATCH", "documents", params={"doc_id": f"eq.{doc_id}", "status": "eq.deleted"},
                           body={"cleanup_after": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})


def get_document_repository() -> DocumentRepository:
    return DocumentRepository(get_config())
