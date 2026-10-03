"""
PDF text extraction with pypdf and recursive text splitting.

Processors handle document I/O only; embeddings and vector storage live in providers/ and storage/.
"""
import logging
import os

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.core.config import get_config

logger = logging.getLogger(__name__)


def load_pdf_pages(
    file_path: str,
    *,
    original_filename: str | None = None,
) -> tuple[list[Document], list[str]]:
    """
    Return physical PDF pages with one-based metadata and extraction warnings.
    Handles corrupt file (raises); detects likely scanned PDF (adds warning).

    When loading from a temp path, pass ``original_filename`` so chunk metadata keeps the real PDF name.
    """
    config = get_config()
    warnings: list[str] = []
    source_name = original_filename or os.path.basename(file_path)
    try:
        with open(file_path, "rb") as file:
            reader = PdfReader(file)
            docs = [
                Document(page_content=(page.extract_text() or "").strip(),
                         metadata={"source": source_name, "page": number})
                for number, page in enumerate(reader.pages, 1)
            ]
    except Exception as e:
        logger.exception("PDF load failed for %s: %s", file_path, e)
        raise ValueError(f"PDF file is corrupt or unreadable: {e!s}") from e

    if not docs:
        raise ValueError("PDF produced no pages (empty or unreadable).")

    low_text_pages = sum(len(doc.page_content) < config.min_chars_per_page for doc in docs)

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
    Returns list of dicts with keys: text, page, source for Milvus.
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
        chunks.append({
            "text": d.page_content,
            "page": d.metadata["page"],
            "source": d.metadata["source"],
        })
    logger.info(
        "Chunking produced %s chunks (chunk_size=%s, chunk_overlap=%s)",
        len(chunks),
        resolved_chunk_size,
        resolved_chunk_overlap,
    )
    return chunks
