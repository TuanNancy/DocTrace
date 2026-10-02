"""
POST /api/upload: retain a multipart PDF and return 202 with queued document metadata.
"""
import logging
import uuid
from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.auth import require_supabase_user
from app.core.config import get_config
from app.core.limits import require_upload_slot
from app.services.document_repository import DocumentRepository, get_document_repository, public_document
from app.services.supabase_pdf_storage import build_pdf_object_key, upload_pdf_to_supabase_storage, is_pdf_storage_configured

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload", status_code=202)
async def upload_pdf(
    file: Annotated[UploadFile, File(description="PDF file to index")],
    user: dict = Depends(require_supabase_user),
    _slot: None = Depends(require_upload_slot),
    repository: DocumentRepository = Depends(get_document_repository),
) -> Dict[str, Any]:
    """
    Retain a PDF and enqueue durable indexing. The worker owns extraction/embedding.
    """
    config = get_config()

    # Validate content type
    content_type = file.content_type or ""
    if content_type.split(";")[0].strip().lower() not in (
        ct.lower() for ct in config.upload_allowed_content_types
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {content_type}. Allowed: {list(config.upload_allowed_content_types)}",
        )

    # Validate filename
    filename = file.filename or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must have .pdf extension.")

    # Read and validate size
    max_bytes = config.upload_max_size_mb * 1024 * 1024
    chunks_read = []
    total_size = 0

    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size: {config.upload_max_size_mb} MB.",
            )
        chunks_read.append(chunk)

    file_content = b"".join(chunks_read)

    if not file_content:
        raise HTTPException(status_code=400, detail="Empty file.")
    if not file_content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Invalid PDF header.")
    if not is_pdf_storage_configured():
        raise HTTPException(503, "Kho PDF chưa được cấu hình trên máy chủ.")

    uid = str(user.get("id") or "")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid user: missing id.")
    doc_id = str(uuid.uuid4())

    key = build_pdf_object_key(uid, doc_id, filename)
    await repository.create({"doc_id": doc_id, "user_id": uid, "name": filename,
                             "size_bytes": total_size, "storage_key": key, "status": "uploading"})
    try:
        await run_in_threadpool(upload_pdf_to_supabase_storage, file_content, key)
        document = await repository.queue(uid, doc_id, "index")
    except Exception as e:
        logger.exception("PDF retention/enqueue failed")
        try:
            await repository.upload_failed(uid, doc_id)
        except Exception:
            logger.exception("Could not record failed upload; stale-upload recovery will handle it")
        raise HTTPException(503, "Không thể lưu hoặc xếp hàng tài liệu. Vui lòng kiểm tra thư viện và thử lại.") from e
    return public_document(document)
