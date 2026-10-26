"""
Pydantic request/response models for API.
"""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """Request body for POST /api/chat."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(..., min_length=1, max_length=8000, description="User question")
    doc_id: str = Field(..., min_length=1, max_length=64, description="Document ID from upload response")
    language: Literal["vi", "en"] = "vi"


class WorkspaceCreate(BaseModel):
    """Create a team workspace owned by the current user."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(..., min_length=1, max_length=80)


class WorkspaceMemberAdd(BaseModel):
    """Add an existing user to a workspace; demo has no email delivery."""

    model_config = ConfigDict(extra="forbid")
    user_id: UUID
