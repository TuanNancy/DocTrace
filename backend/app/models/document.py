"""
Document models for data structures.
Defines the core data models for documents, chunks, and query results.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
    AUTO = "auto"  # Automatic processing
    RAG = "rag"    # Retrieval-Augmented Generation
    DIRECT = "direct"  # Direct LLM query without retrieval


class TaskStatus(str, Enum):
    """Status of agent tasks."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


# ==================== Document Models ====================

@dataclass
class DocumentChunk:
    """
    Represents a single chunk of text from a document.

    Chunks are the basic units of text that are embedded and stored
    in the vector database for retrieval.
    """
    chunk_id: str
    doc_id: str
    text: str
    page: int
    source: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert chunk to dictionary."""
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "text": self.text,
            "page": self.page,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "metadata": self.metadata,
        }


@dataclass
class Document:
    """
    Represents a complete document with all its chunks.

    A document can be a PDF, text file, or other supported format
    that has been processed and indexed.
    """
    doc_id: str
    name: str
    source: str
    chunks_count: int
    status: DocumentStatus
    created_at: datetime
    updated_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert document to dictionary."""
        return {
            "doc_id": self.doc_id,
            "name": self.name,
            "source": self.source,
            "chunks_count": self.chunks_count,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "metadata": self.metadata,
        }

    @property
    def is_completed(self) -> bool:
        """Check if document processing is completed."""
        return self.status == DocumentStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        """Check if document processing has failed."""
        return self.status == DocumentStatus.FAILED


@dataclass
class RetrievedChunk:
    """
    Represents a chunk retrieved from vector search.

    Includes relevance score and metadata for ranking and display.
    """
    chunk_id: str
    doc_id: str
    text: str
    page: int
    source: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert retrieved chunk to dictionary."""
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "text": self.text,
            "page": self.page,
            "source": self.source,
            "score": round(self.score, 4),
            "metadata": self.metadata,
        }

    def get_citation(self) -> str:
        """Generate a citation string for this chunk."""
        return f"[{self.source} - trang {self.page}]"


# ==================== Query Models ====================

@dataclass
class QueryResult:
    """
    Result of a RAG query operation.

    Contains the answer, retrieved chunks, and metadata about
    the query processing.
    """
    query: str
    answer: str
    retrieved_chunks: List[RetrievedChunk]
    mode: QueryMode
    processing_time: float
    created_at: datetime
    total_cost: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert query result to dictionary."""
        return {
            "query": self.query,
            "answer": self.answer,
            "retrieved_chunks": [c.to_dict() for c in self.retrieved_chunks],
            "mode": self.mode.value,
            "processing_time": round(self.processing_time, 3),
            "created_at": self.created_at.isoformat(),
            "total_cost": round(self.total_cost, 6),
            "metadata": self.metadata,
        }

    def get_sources(self) -> List[str]:
        """Get unique sources from retrieved chunks."""
        return list({c.source for c in self.retrieved_chunks})

    def get_pages(self) -> List[int]:
        """Get unique page numbers from retrieved chunks."""
        return sorted({c.page for c in self.retrieved_chunks})

    def get_citations(self) -> List[str]:
        """Get citation strings for all retrieved chunks."""
        return [c.get_citation() for c in self.retrieved_chunks]


# ==================== Processing Models ====================

@dataclass
class IndexingResult:
    """
    Result of document indexing operation.

    Contains information about the indexing process including
    the document ID, number of chunks, and any warnings.
    """
    doc_id: str
    name: str
    chunks_count: int
    status: DocumentStatus
    processing_time: float
    created_at: datetime
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert indexing result to dictionary."""
        return {
            "doc_id": self.doc_id,
            "name": self.name,
            "chunks_count": self.chunks_count,
            "status": self.status.value,
            "processing_time": round(self.processing_time, 3),
            "created_at": self.created_at.isoformat(),
            "warnings": self.warnings,
            "metadata": self.metadata,
        }

    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0


# ==================== Pydantic Models for API ====================

class DocumentChunkResponse(BaseModel):
    """Pydantic model for document chunk API responses."""
    chunk_id: str = Field(..., description="Unique chunk identifier")
    doc_id: str = Field(..., description="Parent document ID")
    text: str = Field(..., description="Chunk text content")
    page: int = Field(..., description="Page number in source document")
    source: str = Field(..., description="Source document name")
    score: Optional[float] = Field(None, description="Relevance score (for retrieved chunks)")

    class Config:
        json_schema_extra = {
            "example": {
                "chunk_id": "uuid-1234",
                "doc_id": "doc-5678",
                "text": "Sample chunk text content...",
                "page": 1,
                "source": "document.pdf",
                "score": 0.95,
            }
        }


class DocumentResponse(BaseModel):
    """Pydantic model for document API responses."""
    doc_id: str = Field(..., description="Unique document identifier")
    name: str = Field(..., description="Document name")
    source: str = Field(..., description="Document source path")
    chunks_count: int = Field(..., description="Number of chunks")
    status: str = Field(..., description="Document processing status")
    created_at: str = Field(..., description="Creation timestamp (ISO format)")
    updated_at: Optional[str] = Field(None, description="Last update timestamp (ISO format)")

    class Config:
        json_schema_extra = {
            "example": {
                "doc_id": "doc-5678",
                "name": "document.pdf",
                "source": "/path/to/document.pdf",
                "chunks_count": 42,
                "status": "completed",
                "created_at": "2024-01-15T10:30:00",
                "updated_at": "2024-01-15T10:35:00",
            }
        }


class QueryResponse(BaseModel):
    """Pydantic model for query API responses."""
    query: str = Field(..., description="Original query")
    answer: str = Field(..., description="Generated answer")
    sources: List[DocumentChunkResponse] = Field(..., description="Retrieved source chunks")
    processing_time: float = Field(..., description="Processing time in seconds")
    mode: str = Field(..., description="Query processing mode")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "What is the main topic?",
                "answer": "The main topic is about...",
                "sources": [
                    {
                        "chunk_id": "uuid-1234",
                        "doc_id": "doc-5678",
                        "text": "Sample chunk text...",
                        "page": 1,
                        "source": "document.pdf",
                        "score": 0.95,
                    }
                ],
                "processing_time": 1.234,
                "mode": "rag",
            }
        }


# ==================== Utility Functions ====================

def create_document_chunk(
    doc_id: str,
    text: str,
    page: int,
    source: str,
    chunk_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> DocumentChunk:
    """
    Factory function to create a DocumentChunk.

    Args:
        doc_id: Document identifier
        text: Chunk text content
        page: Page number
        source: Source document name
        chunk_id: Optional chunk ID (generated if not provided)
        metadata: Optional metadata dictionary

    Returns:
        DocumentChunk instance
    """
    import uuid

    return DocumentChunk(
        chunk_id=chunk_id or str(uuid.uuid4()),
        doc_id=doc_id,
        text=text,
        page=page,
        source=source,
        created_at=datetime.utcnow(),
        metadata=metadata or {},
    )


def create_retrieved_chunk(
    chunk: DocumentChunk,
    score: float
) -> RetrievedChunk:
    """
    Factory function to create a RetrievedChunk from a DocumentChunk.

    Args:
        chunk: Source DocumentChunk
        score: Relevance score

    Returns:
        RetrievedChunk instance
    """
    return RetrievedChunk(
        chunk_id=chunk.chunk_id,
        doc_id=chunk.doc_id,
        text=chunk.text,
        page=chunk.page,
        source=chunk.source,
        score=score,
        metadata=chunk.metadata.copy(),
    )


def create_query_result(
    query: str,
    answer: str,
    retrieved_chunks: List[RetrievedChunk],
    mode: QueryMode = QueryMode.RAG,
    processing_time: float = 0.0,
    total_cost: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None
) -> QueryResult:
    """
    Factory function to create a QueryResult.

    Args:
        query: Original query string
        answer: Generated answer
        retrieved_chunks: List of retrieved chunks
        mode: Query processing mode
        processing_time: Processing time in seconds
        total_cost: Total API cost
        metadata: Optional metadata dictionary

    Returns:
        QueryResult instance
    """
    return QueryResult(
        query=query,
        answer=answer,
        retrieved_chunks=retrieved_chunks,
        mode=mode,
        processing_time=processing_time,
        created_at=datetime.utcnow(),
        total_cost=total_cost,
        metadata=metadata or {},
    )
