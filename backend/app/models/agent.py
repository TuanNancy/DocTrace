"""
Conversation models (lightweight).

This module intentionally does NOT implement multi-agent task planning/orchestration.
Legacy task/plan models were removed to keep the codebase focused on standard RAG.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ==================== Enums ====================

class MessageRole(str, Enum):
    """Role of a message in conversation."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ConversationState(str, Enum):
    """State of conversation processing."""
    ACTIVE = "active"
    SUMMARIZED = "summarized"
    ARCHIVED = "archived"


# ==================== Conversation Models ====================

@dataclass
class ConversationMessage:
    """
    Represents a single message in a conversation.

    Tracks the role, content, timestamp, and cost for each message
    in the conversation history.
    """
    role: MessageRole
    content: str
    timestamp: datetime
    message_id: str
    cost: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary."""
        return {
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "message_id": self.message_id,
            "cost": round(self.cost, 6),
            "metadata": self.metadata,
        }

    def to_openai_format(self) -> Dict[str, str]:
        """Convert to OpenAI message format."""
        return {
            "role": self.role.value,
            "content": self.content,
        }

    @property
    def is_user(self) -> bool:
        """Check if message is from user."""
        return self.role == MessageRole.USER

    @property
    def is_assistant(self) -> bool:
        """Check if message is from assistant."""
        return self.role == MessageRole.ASSISTANT

    @property
    def is_system(self) -> bool:
        """Check if message is a system message."""
        return self.role == MessageRole.SYSTEM


@dataclass
class ConversationSummary:
    """
    Represents a summary of a conversation.

    Contains condensed information about a conversation for context
    management and memory efficiency.
    """
    conversation_id: str
    summary: str
    message_count: int
    created_at: datetime
    updated_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert summary to dictionary."""
        return {
            "conversation_id": self.conversation_id,
            "summary": self.summary,
            "message_count": self.message_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class ConversationContext:
    """
    Represents the processed context for a conversation.

    Contains both the full recent messages and a summary of older
    messages for efficient context management.
    """
    conversation_id: str
    recent_messages: List[ConversationMessage]
    summary: Optional[ConversationSummary]
    total_message_count: int
    processed_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary."""
        return {
            "conversation_id": self.conversation_id,
            "recent_messages": [m.to_dict() for m in self.recent_messages],
            "summary": self.summary.to_dict() if self.summary else None,
            "total_message_count": self.total_message_count,
            "processed_at": self.processed_at.isoformat(),
        }

    def get_messages_for_llm(self) -> List[Dict[str, str]]:
        """Get messages formatted for LLM API."""
        messages = []

        # Add summary as system message if available
        if self.summary:
            messages.append({
                "role": "system",
                "content": f"Previous conversation summary:\n{self.summary.summary}"
            })

        # Add recent messages
        for msg in self.recent_messages:
            messages.append(msg.to_openai_format())

        return messages


# ==================== Pydantic Models for API ====================

class ConversationMessageResponse(BaseModel):
    """Pydantic model for conversation message API responses."""
    role: str = Field(..., description="Message role (system, user, assistant)")
    content: str = Field(..., description="Message content")
    timestamp: str = Field(..., description="Message timestamp (ISO format)")
    message_id: str = Field(..., description="Unique message identifier")
    cost: float = Field(default=0.0, description="Cost of this message")

    class Config:
        json_schema_extra = {
            "example": {
                "role": "user",
                "content": "What is the main topic?",
                "timestamp": "2024-01-15T10:30:00",
                "message_id": "msg-1234",
                "cost": 0.0001,
            }
        }


# ==================== Utility Functions ====================

def create_conversation_message(
    role: MessageRole,
    content: str,
    message_id: Optional[str] = None,
    cost: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None
) -> ConversationMessage:
    """
    Factory function to create a ConversationMessage.

    Args:
        role: Message role
        content: Message content
        message_id: Optional message ID (generated if not provided)
        cost: Cost of this message
        metadata: Optional metadata dictionary

    Returns:
        ConversationMessage instance
    """
    import uuid

    return ConversationMessage(
        role=role,
        content=content,
        timestamp=datetime.utcnow(),
        message_id=message_id or str(uuid.uuid4()),
        cost=cost,
        metadata=metadata or {},
    )


# ==================== Backward-compat stubs (removed legacy task/plan API) ====================

class _RemovedLegacyTaskModels:
    def __init__(self, *_: Any, **__: Any) -> None:
        raise RuntimeError(
            "Legacy task/plan models were removed. "
            "Use the standard RAG pipeline (app.ai.rag_agent.RAGAgent) instead."
        )


# Keep these names importable for old code paths. They are not functional.
TaskType = _RemovedLegacyTaskModels  # type: ignore
AgentTask = _RemovedLegacyTaskModels  # type: ignore
TaskPlan = _RemovedLegacyTaskModels  # type: ignore
TaskResult = _RemovedLegacyTaskModels  # type: ignore
AgentQueryResult = _RemovedLegacyTaskModels  # type: ignore

AgentTaskResponse = _RemovedLegacyTaskModels  # type: ignore
TaskPlanResponse = _RemovedLegacyTaskModels  # type: ignore

def create_agent_task(*_: Any, **__: Any) -> Any:  # type: ignore
    raise RuntimeError("create_agent_task was removed. Use RAGAgent instead.")

def create_task_plan(*_: Any, **__: Any) -> Any:  # type: ignore
    raise RuntimeError("create_task_plan was removed. Use RAGAgent instead.")

def create_task_result(*_: Any, **__: Any) -> Any:  # type: ignore
    raise RuntimeError("create_task_result was removed. Use RAGAgent instead.")

def create_agent_query_result(*_: Any, **__: Any) -> Any:  # type: ignore
    raise RuntimeError("create_agent_query_result was removed. Use RAGAgent instead.")
