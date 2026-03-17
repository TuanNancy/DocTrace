"""
Deprecated legacy module.

Retrieval is implemented via:
- `app.storage.*` (vector search)
- `app.ai.rag_agent` (end-to-end query processing)

This file remains only to avoid breaking old imports.
"""
from typing import Any


class RetrievedChunk:  # backward-compat placeholder
    def __init__(self, *_: Any, **__: Any) -> None:
        raise RuntimeError(
            "app.documents.retrieval.RetrievedChunk is deprecated and was removed. "
            "Use app.models.document.RetrievedChunk (storage result) instead."
        )


def search_chunks(*_: Any, **__: Any) -> Any:  # backward-compat placeholder
    raise RuntimeError(
        "app.documents.retrieval.search_chunks is deprecated and was removed. "
        "Use app.ai.rag_agent.RAGAgent or app.storage.* instead."
    )


def build_context(*_: Any, **__: Any) -> Any:  # backward-compat placeholder
    raise RuntimeError(
        "app.documents.retrieval.build_context is deprecated and was removed. "
        "Use app.ai.rag_agent.RAGAgent (internal context builder) instead."
    )

