"""
Document processors: PDF loading, chunking (see STRUCTURE.md).
"""

from app.processors.pdf import chunk_documents, load_pdf_pages

__all__ = ["chunk_documents", "load_pdf_pages"]
