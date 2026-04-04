"""
Document models for data structures used in the RAG pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class DocumentStatus(str, Enum):
    COMPLETED = "completed"


@dataclass
class IndexingResult:
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
