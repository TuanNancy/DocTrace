"""
Deprecated stubs. Retrieval is implemented via app.storage.* and app.ai.rag_agent.
"""
from typing import Any


class RetrievedChunk:  # backward-compat placeholder
    def __init__(self, *_: Any, **__: Any) -> None:
        raise RuntimeError(
            "app.processors.legacy_retrieval.RetrievedChunk is deprecated. "
            "Use app.models.document.RetrievedChunk (storage result) instead."
        )


def search_chunks(*_: Any, **__: Any) -> Any:
    raise RuntimeError(
        "search_chunks is deprecated. Use app.ai.rag_agent.RAGAgent or app.storage.* instead."
    )


def build_context(*_: Any, **__: Any) -> Any:
    raise RuntimeError(
        "build_context is deprecated. Use app.ai.rag_agent.RAGAgent instead."
    )
