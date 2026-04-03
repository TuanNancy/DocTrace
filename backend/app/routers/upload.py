"""
POST /api/upload: multipart/form-data PDF upload → indexing pipeline → UploadResponse.
Updated to use new architecture with storage factory and document models.
"""
import asyncio
import logging
import time
import uuid
from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core.auth import require_supabase_user
from app.core.config import get_config
from app.models.document import DocumentStatus, IndexingResult, create_indexing_result
from app.services.supabase_pdf_storage import try_upload_pdf
from app.storage.factory import create_and_connect_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["upload"])


async def run_indexing_pipeline_from_upload(
    file_content: bytes,
    filename: str,
    doc_id: str,
) -> IndexingResult:
    """
    Run indexing pipeline on uploaded file content.

    This function:
    1. Loads PDF and extracts text
    2. Chunks the text
    3. Embeds chunks
    4. Inserts into vector database

    Args:
        file_content: PDF file content as bytes
        filename: Original filename
        doc_id: Pre-generated document ID used for both S3 key and Milvus rows

    Returns:
        IndexingResult with doc_id, chunks_count, and warnings
    """
    import os
    import tempfile

    from app.core.config import get_config
    from app.processors.pdf import chunk_documents, load_pdf_pages
    from app.providers.embeddings import get_embedder

    config = get_config()
    start_time = time.time()

    # Create temporary file
    suffix = os.path.splitext(filename)[1] or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(file_content)
        temp_path = f.name

    try:
        docs, warnings = load_pdf_pages(temp_path, original_filename=filename)
        chunks = chunk_documents(docs)

        if not chunks:
            raise ValueError("No text chunks produced from PDF.")

        # Embed chunks (dimension must match Milvus collection — use len(vectors[0]), not a guessed probe default)
        embedder = get_embedder()
        vectors = embedder.embed_documents([c["text"] for c in chunks])

        if len(vectors) != len(chunks):
            raise RuntimeError("Embedding count does not match chunk count.")
        if not vectors or not vectors[0]:
            raise RuntimeError("Embedding API returned empty vectors.")

        vector_dim = len(vectors[0])
        if embedder.dimension != vector_dim:
            logger.warning(
                "Embedder.dimension=%s differs from actual vector length=%s; using vector length for Milvus.",
                embedder.dimension,
                vector_dim,
            )

        # Insert into storage
        storage = await create_and_connect_storage()
        try:
            # Ensure collection exists (recreates if existing schema dim mismatches)
            await storage.ensure_collection(vector_dim=vector_dim)

            # Insert chunks
            insert_result = await storage.insert_chunks(
                doc_id=doc_id,
                chunks=chunks,
                vectors=vectors,
            )
        finally:
            await storage.disconnect()

        processing_time = time.time() - start_time

        merged_warnings: list[str] = []
        if warnings:
            merged_warnings.extend(warnings)
        if insert_result.warnings:
            merged_warnings.extend(insert_result.warnings)

        return create_indexing_result(
            doc_id=doc_id,
            name=filename,
            chunks_count=insert_result.chunks_inserted,
            status=DocumentStatus.COMPLETED,
            processing_time=processing_time,
            warnings=merged_warnings,
        )

    finally:
        # Clean up temp file
        try:
            os.unlink(temp_path)
        except OSError:
            pass


@router.post("/upload")
async def upload_pdf(
    file: Annotated[UploadFile, File(description="PDF file to index")],
    user: dict = Depends(require_supabase_user),
) -> Dict[str, Any]:
    """
    Accept a PDF via multipart/form-data, validate size/type, run indexing pipeline,
    return doc_id and chunks count. Handles errors gracefully.

    Updated to use new architecture with storage factory and document models.
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
        result = await run_indexing_pipeline_from_upload(file_content, filename, doc_id)
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
