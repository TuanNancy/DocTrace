"""
POST /api/upload: multipart/form-data PDF upload → indexing pipeline → UploadResponse.
"""
import asyncio
import logging
import uuid
from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core.auth import require_supabase_user
from app.core.config import get_config
from app.services.pdf_indexing import index_pdf_bytes
from app.services.supabase_pdf_storage import try_upload_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload")
async def upload_pdf(
    file: Annotated[UploadFile, File(description="PDF file to index")],
    user: dict = Depends(require_supabase_user),
) -> Dict[str, Any]:
    """
    Accept a PDF via multipart/form-data, validate size/type, run indexing pipeline,
    return doc_id and chunks count. Handles errors gracefully.

    Delegates PDF indexing to services.pdf_indexing.index_pdf_bytes.
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

    uid = str(user.get("id") or "")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid user: missing id.")
    doc_id = str(uuid.uuid4())

    # Store original PDF early so users can still find the file in Storage
    # even if downstream indexing (Milvus/embeddings) fails.
    pdf_key, storage_warn = await asyncio.to_thread(
        try_upload_pdf,
        file_content,
        uid,
        doc_id,
        filename,
    )

    try:
        result = await index_pdf_bytes(file_content, filename, doc_id)
        if storage_warn:
            result.warnings.append(storage_warn)
        if pdf_key:
            result.pdf_storage_key = pdf_key
            logger.info("PDF storage key set in response: %s", pdf_key)
        else:
            logger.info("PDF storage key is None — S3 upload was skipped or failed")
    except ValueError as e:
        logger.warning("Indexing validation error: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Indexing failed: %s", e)
        # Surface cause for debugging (API/Milvus/dim); PDF issues usually raise ValueError → 400 above
        msg = str(e).strip() or repr(e)
        if len(msg) > 500:
            msg = msg[:500] + "…"
        raise HTTPException(
            status_code=500,
            detail=f"Indexing failed: {msg}",
        ) from e

    return result.to_dict()
