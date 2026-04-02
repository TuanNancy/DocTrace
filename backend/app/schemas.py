"""
Pydantic request/response models for API.
"""
from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    """Response after successful PDF upload and indexing."""

    doc_id: str = Field(..., description="Unique document ID assigned to the uploaded PDF")
    chunks_count: int = Field(..., description="Number of chunks created and inserted")
    message: str = Field(default="Upload and indexing completed.", description="Status message")


class ChatRequest(BaseModel):
    """Request body for POST /api/chat (RAG over one document)."""

    query: str = Field(..., min_length=1, description="User question")
    doc_id: str = Field(..., min_length=1, description="Document ID from upload response")
    language: str = Field(default="vi", description="Response language (vi or en)")


class ErrorDetail(BaseModel):
    """Structured error for API responses."""

    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Human-readable message")
    detail: str | None = Field(None, description="Optional extra detail")
