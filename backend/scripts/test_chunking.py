"""
Test chunking on PDF files.
Run from backend: python scripts/test_chunking.py <path_to_pdf> [path_to_pdf2]
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.processors.pdf import chunk_documents, load_pdf_pages

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def test_pdf(path: str) -> None:
    docs, warnings = load_pdf_pages(path)
    chunks = chunk_documents(docs)
    logger.info("PDF: %s -> pages=%s, chunks=%s", path, len(docs), len(chunks))
    for w in warnings:
        logger.warning("  %s", w)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_chunking.py <pdf1> [pdf2]")
        sys.exit(1)
    for p in sys.argv[1:]:
        test_pdf(p)
