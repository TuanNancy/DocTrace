"""
Document models for data structures used in the RAG pipeline.
Only contains models that are actually used by routers, agents, or storage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# ==================== Enums ====================

class DocumentStatus(str, Enum):
    """Status of document processing."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETING = "deleting"


class QueryMode(str, Enum):
    """Mode for query processing."""
    AUTO = "auto"
    RAG = "rag"
    DIRECT = "direct"


# ==================== Dataclasses ====================

@dataclass
class RetrievedChunk:
    """Chunk retrieved from vector search with relevance score."""
    chunk_id: str
    doc_id: str
    text: str
    page: int
    source: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryResult:
    """Result of a RAG query operation."""
    query: str
    answer: str
    retrieved_chunks: List[RetrievedChunk]
    mode: QueryMode
    processing_time: float
    total_cost: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class IndexingResult:
    """Result of document indexing operation."""
    doc_id: str
    name: str
    chunks_count: int
    status: DocumentStatus
    processing_time: float
    warnings: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    pdf_storage_key: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "doc_id": self.doc_id,
            "name": self.name,
            "chunks_count": self.chunks_count,
            "status": self.status.value,
            "processing_time": round(self.processing_time, 3),
            "created_at": self.created_at.isoformat(),
        }
        if self.warnings:
            out["warnings"] = self.warnings
        if self.pdf_storage_key is not None:
            out["pdf_storage_key"] = self.pdf_storage_key
        return out


# ==================== Factory Functions ====================

def create_query_result(
    query: str,
    answer: str,
    retrieved_chunks: List[RetrievedChunk],
    mode: QueryMode,
    processing_time: float,
    total_cost: float = 0.0,
) -> QueryResult:
    return QueryResult(
        query=query,
        answer=answer,
        retrieved_chunks=retrieved_chunks,
        mode=mode,
        processing_time=processing_time,
        total_cost=total_cost,
    )


def create_indexing_result(
    doc_id: str,
    name: str,
    chunks_count: int,
    status: DocumentStatus,
    processing_time: float,
    warnings: Optional[List[str]] = None,
    pdf_storage_key: Optional[str] = None,
) -> IndexingResult:
    return IndexingResult(
        doc_id=doc_id,
        name=name,
        chunks_count=chunks_count,
        status=status,
        processing_time=processing_time,
        warnings=warnings or [],
        pdf_storage_key=pdf_storage_key,
    )
