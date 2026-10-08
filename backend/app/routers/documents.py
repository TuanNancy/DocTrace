"""Owner-scoped document library, lifecycle operations and source navigation."""
from uuid import UUID

from anyio import CancelScope
from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from app.core.auth import require_supabase_user
from app.services.document_repository import DocumentRepository, get_document_repository, public_document
from app.services.supabase_pdf_storage import signed_pdf_url
from app.services.rate_limiter import RateLimiter, get_rate_limiter
from app.storage.factory import create_connected_vector_store

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("")
async def list_documents(limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0),
                         user: dict = Depends(require_supabase_user),
                         repository: DocumentRepository = Depends(get_document_repository)):
    return await repository.list(user["id"], limit, offset)


@router.get("/{doc_id}")
async def get_document(doc_id: UUID, user: dict = Depends(require_supabase_user),
                       repository: DocumentRepository = Depends(get_document_repository)):
    return public_document(await repository.get(user["id"], str(doc_id)))


@router.post("/{doc_id}/retry", status_code=202)
async def retry_document(doc_id: UUID, user: dict = Depends(require_supabase_user),
                         repository: DocumentRepository = Depends(get_document_repository),
                         limiter: RateLimiter = Depends(get_rate_limiter)):
    document = await repository.get(user["id"], str(doc_id))
    if document["status"] not in ("error", "delete_error"):
        raise HTTPException(409, "Chỉ có thể thử lại tài liệu bị lỗi.")
    if document["status"] == "error":
        await limiter.check(user["id"], action="index-retry")
    return public_document(await repository.queue(user["id"], str(doc_id),
                           "delete" if document["status"] == "delete_error" else "index"))


@router.delete("/{doc_id}", status_code=202)
async def delete_document(doc_id: UUID, user: dict = Depends(require_supabase_user),
                          repository: DocumentRepository = Depends(get_document_repository)):
    return public_document(await repository.queue(user["id"], str(doc_id), "delete"))


@router.get("/{doc_id}/file")
async def document_file(doc_id: UUID, user: dict = Depends(require_supabase_user),
                         repository: DocumentRepository = Depends(get_document_repository)):
    document = await repository.get(user["id"], str(doc_id))
    if document["status"] in ("deleting", "delete_error"):
        raise HTTPException(409, "PDF chưa sẵn sàng hoặc đang bị xóa.")
    try:
        url = await run_in_threadpool(signed_pdf_url, document["storage_key"])
    except Exception as exc:
        raise HTTPException(503, "Không thể mở PDF. Vui lòng thử lại.") from exc
    return {"url": url, "expires_in": 300}


@router.get("/{doc_id}/chunks/{chunk_id}")
async def document_chunk(doc_id: UUID, chunk_id: UUID, user: dict = Depends(require_supabase_user),
                          repository: DocumentRepository = Depends(get_document_repository)):
    document = await repository.get(user["id"], str(doc_id))
    if document["status"] != "ready" or not document["active_index_id"]:
        raise HTTPException(409, "Nguồn trích dẫn không còn khả dụng.")
    store = await create_connected_vector_store()
    try:
        chunk = await store.get_chunk(document["active_index_id"], str(chunk_id), user_id=user["id"])
        if not chunk:
            raise HTTPException(404, "Không tìm thấy đoạn trích trong tài liệu này.")
        return {"doc_id": str(doc_id), "chunk_id": chunk.chunk_id, "source": document["name"],
                "page": chunk.page, "text": chunk.text}
    finally:
        with CancelScope(shield=True):
            await store.disconnect()
