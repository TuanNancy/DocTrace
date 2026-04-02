"""
PDF text extraction and chunking (LangChain + PyPDFLoader).

Processors handle document I/O only; embeddings and vector storage live in providers/ and storage/.
"""
import logging
import os

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import get_config

logger = logging.getLogger(__name__)


def _normalize_metadata(doc: Document, source_path: str) -> dict:
    """Ensure page number and source in metadata."""
    meta = dict(doc.metadata)
    if "page" not in meta and "page_number" in meta:
        meta["page"] = meta["page_number"]
    meta.setdefault("page", 0)
    meta.setdefault("source", source_path)
    return meta


def load_pdf_pages(
    file_path: str,
    *,
    original_filename: str | None = None,
) -> tuple[list[Document], list[str]]:
    """
    Load PDF with PyPDFLoader; return (documents with page metadata, list of warnings).
    Handles corrupt file (raises); detects likely scanned PDF (adds warning).

    When loading from a temp path, pass ``original_filename`` so chunk metadata keeps the real PDF name.
    """
    config = get_config()
    warnings: list[str] = []
    try:
        loader = PyPDFLoader(file_path, mode="page")
        docs = loader.load()
    except Exception as e:
        logger.exception("PDF load failed for %s: %s", file_path, e)
        raise ValueError(f"PDF file is corrupt or unreadable: {e!s}") from e

    if not docs:
        raise ValueError("PDF produced no pages (empty or unreadable).")

    source_name = original_filename or os.path.basename(file_path)
    low_text_pages = 0
    for d in docs:
        d.metadata["source"] = d.metadata.get("source") or source_name
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

    return docs, warnings


def chunk_documents(
    documents: list[Document],
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[dict]:
    """
    Split documents with RecursiveCharacterTextSplitter.
    Returns list of dicts with keys: text, page, source (and metadata for Milvus).
    """
    config = get_config()
    resolved_chunk_size = chunk_size if chunk_size is not None else config.chunk_size
    resolved_chunk_overlap = chunk_overlap if chunk_overlap is not None else config.chunk_overlap
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=resolved_chunk_size,
        chunk_overlap=resolved_chunk_overlap,
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
        resolved_chunk_size,
        resolved_chunk_overlap,
    )
    return chunks
