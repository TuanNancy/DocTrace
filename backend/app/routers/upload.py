"""
POST /api/upload: multipart/form-data PDF upload → indexing pipeline → UploadResponse.
Updated to use new architecture with storage factory and document models.
"""
import logging
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import get_config
from app.models.document import DocumentStatus, IndexingResult, create_indexing_result
from app.storage.base import InsertResult
from app.storage.factory import create_and_connect_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["upload"])


async def run_indexing_pipeline_from_upload(
    file_content: bytes,
    filename: str,
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

    Returns:
        IndexingResult with doc_id, chunks_count, and warnings
    """
    import os
    import tempfile
    from datetime import datetime

    from langchain_community.document_loaders import PyPDFLoader
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    from app.core.config import get_config
    from app.providers.embeddings import get_embedder

    config = get_config()
    start_time = time.time()

    # Create temporary file
    suffix = os.path.splitext(filename)[1] or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(file_content)
        temp_path = f.name

    try:
        # Load PDF
        loader = PyPDFLoader(temp_path, mode="page")
        docs = loader.load()

        if not docs:
            raise ValueError("PDF produced no pages (empty or unreadable).")

        # Check for scanned PDF
        warnings = []
        low_text_pages = 0
        for d in docs:
            d.metadata["source"] = d.metadata.get("source") or filename
            d.metadata["page"] = d.metadata.get("page", 0)
            if len((d.page_content or "").strip()) < config.min_chars_per_page:
                low_text_pages += 1

        if low_text_pages / len(docs) >= config.scanned_page_ratio_threshold:
            warnings.append(
                "Many pages have little or no extractable text. This PDF may be scanned; "
                "consider using OCR for better results."
            )
            logger.warning(
                "Possible scanned PDF: %s of %s pages below %s chars",
                low_text_pages,
                len(docs),
                config.min_chars_per_page,
            )

        # Chunk documents
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            length_function=len,
        )
        split_docs = splitter.split_documents(docs)

        chunks = []
        for d in split_docs:
            meta = d.metadata
            chunks.append({
                "text": d.page_content,
                "page": meta.get("page", 0),
                "source": meta.get("source", filename),
            })

        logger.info(
            "Chunking produced %s chunks (chunk_size=%s, chunk_overlap=%s)",
            len(chunks),
            config.chunk_size,
            config.chunk_overlap,
        )

        if not chunks:
            raise ValueError("No text chunks produced from PDF.")

        # Embed chunks
        embedder = get_embedder()
        vectors = embedder.embed_documents([c["text"] for c in chunks])

        if len(vectors) != len(chunks):
            raise RuntimeError("Embedding count does not match chunk count.")

        # Insert into storage
        storage = await create_and_connect_storage()
        doc_id = str(uuid.uuid4())

        # Ensure collection exists
        await storage.ensure_collection(vector_dim=embedder.dimension)

        # Insert chunks
        insert_result = await storage.insert_chunks(
            doc_id=doc_id,
            chunks=chunks,
            vectors=vectors,
        )

        processing_time = time.time() - start_time

        return create_indexing_result(
            doc_id=doc_id,
            name=filename,
            chunks_count=insert_result.chunks_inserted,
            status=DocumentStatus.COMPLETED,
            processing_time=processing_time,
            warnings=warnings or insert_result.warnings,
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
) -> IndexingResult:
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

    try:
        result = await run_indexing_pipeline_from_upload(file_content, filename)
    except ValueError as e:
        logger.warning("Indexing validation error: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Indexing failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Indexing failed. The file may be corrupt or unsupported.",
        ) from e

    return result
