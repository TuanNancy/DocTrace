"""
Pydantic request/response models for API.
"""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request body for POST /api/chat."""

    query: str = Field(..., min_length=1, description="User question")
    doc_id: str = Field(..., min_length=1, description="Document ID from upload response")
    language: str = Field(default="vi", description="Response language (vi or en)")
