"""
Indexing pipeline: PDF load (PyPDFLoader) → chunk (RecursiveCharacterTextSplitter) → embed → Milvus insert.
Handles edge cases: scanned PDF (warn user), corrupt file.
"""
import logging
import os
import tempfile
import uuid
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    MIN_CHARS_PER_PAGE,
)
from app.providers.embeddings import get_embedder
from app.providers.milvus import (
    ensure_collection,
    insert_chunks_batch,
)

logger = logging.getLogger(__name__)

# Threshold: if ratio of "low text" pages exceeds this, treat as likely scanned
SCANNED_PAGE_RATIO_THRESHOLD = 0.5


class IndexingResult:
    """Result of indexing a single PDF."""

    def __init__(
        self,
        doc_id: str,
        chunks_count: int,
        warnings: list[str] | None = None,
    ):
        self.doc_id = doc_id
        self.chunks_count = chunks_count
        self.warnings = warnings or []


def _normalize_metadata(doc: Document, source_path: str) -> dict:
    """Ensure page number and source in metadata."""
    meta = dict(doc.metadata)
    if "page" not in meta and "page_number" in meta:
        meta["page"] = meta["page_number"]
    meta.setdefault("page", 0)
    meta.setdefault("source", source_path)
    return meta


def load_pdf_pages(file_path: str) -> tuple[list[Document], list[str]]:
    """
    Load PDF with PyPDFLoader; return (documents with page metadata, list of warnings).
    Handles corrupt file (raises); detects likely scanned PDF (adds warning).
    """
    warnings: list[str] = []
    try:
        loader = PyPDFLoader(file_path, mode="page")
        docs = loader.load()
    except Exception as e:
        logger.exception("PDF load failed for %s: %s", file_path, e)
        raise ValueError(f"PDF file is corrupt or unreadable: {e!s}") from e

    if not docs:
        raise ValueError("PDF produced no pages (empty or unreadable).")

    source_name = os.path.basename(file_path)
    low_text_pages = 0
    for d in docs:
        d.metadata["source"] = d.metadata.get("source") or source_name
        d.metadata["page"] = d.metadata.get("page", 0)
        if len((d.page_content or "").strip()) < MIN_CHARS_PER_PAGE:
            low_text_pages += 1

    if low_text_pages / len(docs) >= SCANNED_PAGE_RATIO_THRESHOLD:
        warnings.append(
            "Many pages have little or no extractable text. This PDF may be scanned; "
            "consider using OCR for better results."
        )
        logger.warning(
            "Possible scanned PDF: %s of %s pages below %s chars",
            low_text_pages,
            len(docs),
            MIN_CHARS_PER_PAGE,
        )

    return docs, warnings


def chunk_documents(
    documents: list[Document],
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[dict]:
    """
    Split documents with RecursiveCharacterTextSplitter.
    Returns list of dicts with keys: text, page, source (and metadata for Milvus).
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
    )
    split_docs = splitter.split_documents(documents)
    chunks: list[dict] = []
    for d in split_docs:
        meta = _normalize_metadata(d, d.metadata.get("source", ""))
        chunks.append({
            "text": d.page_content,
            "page": meta.get("page", 0),
            "source": meta.get("source", ""),
        })
    logger.info(
        "Chunking produced %s chunks (chunk_size=%s, chunk_overlap=%s)",
        len(chunks),
        chunk_size,
        chunk_overlap,
    )
    return chunks


def run_indexing_pipeline(file_path: str) -> IndexingResult:
    """
    Full pipeline: load PDF → chunk → embed → Milvus batch insert.
    Returns IndexingResult with doc_id, chunks_count, and optional warnings.
    """
    doc_id = str(uuid.uuid4())
    docs, load_warnings = load_pdf_pages(file_path)
    chunks = chunk_documents(docs)
    if not chunks:
        raise ValueError("No text chunks produced from PDF.")

    embedder = get_embedder()
    vectors = embedder.embed_documents([c["text"] for c in chunks])
    if len(vectors) != len(chunks):
        raise RuntimeError("Embedding count does not match chunk count.")

    collection = ensure_collection(vector_dim=embedder.dimension)
    inserted = insert_chunks_batch(doc_id=doc_id, chunks=chunks, vectors=vectors)

    return IndexingResult(
        doc_id=doc_id,
        chunks_count=inserted,
        warnings=load_warnings,
    )


def run_indexing_pipeline_from_upload(file_content: bytes, filename: str) -> IndexingResult:
    """
    Run pipeline on in-memory file content (e.g. from FastAPI UploadFile).
    Writes to a temp file and calls run_indexing_pipeline.
    """
    suffix = Path(filename).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(file_content)
        temp_path = f.name
    try:
        return run_indexing_pipeline(temp_path)
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass

