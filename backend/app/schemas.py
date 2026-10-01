"""
Pydantic request/response models for API.
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """Request body for POST /api/chat."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(..., min_length=1, max_length=8000, description="User question")
    doc_id: str = Field(..., min_length=1, max_length=64, description="Document ID from upload response")
    language: Literal["vi", "en"] = "vi"
