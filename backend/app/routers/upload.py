"""
POST /api/upload: multipart/form-data PDF upload → indexing pipeline → UploadResponse.
"""
import logging
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.config import UPLOAD_ALLOWED_CONTENT_TYPES, UPLOAD_MAX_SIZE_MB
from app.documents.indexing import run_indexing_pipeline_from_upload
from app.schemas import UploadResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["upload"])

MAX_BYTES = UPLOAD_MAX_SIZE_MB * 1024 * 1024


@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(
    file: Annotated[UploadFile, File(description="PDF file to index")],
) -> UploadResponse:
    """
    Accept a PDF via multipart/form-data, validate size/type, run indexing pipeline,
    return doc_id and chunks count. Handles errors gracefully.
    """
    # Validate content type
    content_type = file.content_type or ""
    if content_type.split(";")[0].strip().lower() not in (
        ct.lower() for ct in UPLOAD_ALLOWED_CONTENT_TYPES
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {content_type}. Allowed: {list(UPLOAD_ALLOWED_CONTENT_TYPES)}",
        )

    # Validate filename
    filename = file.filename or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must have .pdf extension.")

    # Read and validate size (stream to avoid loading huge files)
    chunks_read = []
    total_size = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size: {UPLOAD_MAX_SIZE_MB} MB.",
            )
        chunks_read.append(chunk)
    file_content = b"".join(chunks_read)

    if not file_content:
        raise HTTPException(status_code=400, detail="Empty file.")

    try:
        result = run_indexing_pipeline_from_upload(file_content, filename)
    except ValueError as e:
        logger.warning("Indexing validation error: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Indexing failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Indexing failed. The file may be corrupt or unsupported.",
        ) from e

    message = "Upload and indexing completed."
    if result.warnings:
        message += " " + " ".join(result.warnings)

    return UploadResponse(
        doc_id=result.doc_id,
        chunks_count=result.chunks_count,
        message=message,
    )
