"""
Legacy package path. Prefer:

- `app.processors` — PDF / chunking
- `app.storage` — vector retrieval
- `app.ai` — RAG workflows
"""

from app.processors.pdf import chunk_documents, load_pdf_pages

__all__ = ["chunk_documents", "load_pdf_pages"]
