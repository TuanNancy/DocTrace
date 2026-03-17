"""
Deprecated legacy module.

The current API flow uses:
- `app.routers.upload` for PDF upload + indexing
- `app.ai.rag_agent` + `app.storage.*` for retrieval + answering

Only a small subset of pure text utilities may remain here for backward compatibility
(e.g. scripts importing `chunk_documents`, `load_pdf_pages`).
"""

