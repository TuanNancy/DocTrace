"""Backward compatibility: use `app.processors.legacy_retrieval` instead."""

from app.processors.legacy_retrieval import RetrievedChunk, build_context, search_chunks

__all__ = ["RetrievedChunk", "build_context", "search_chunks"]
