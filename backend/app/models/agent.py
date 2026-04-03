"""
Conversation models for managing chat history.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class MessageRole(str, Enum):
    """Message role in conversation."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class ConversationMessage:
    """A single message in the conversation history."""
    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationSummary:
    """Summary of older conversation messages."""
    summary_text: str
    message_count: int
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ConversationContext:
    """Context for LLM: recent messages + optional summary of older ones."""
    conversation_id: str
    recent_messages: List[ConversationMessage]
    summary: Optional[ConversationSummary] = None
    total_message_count: int = 0
    processed_at: datetime = field(default_factory=datetime.utcnow)


def create_conversation_message(
    role: MessageRole,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> ConversationMessage:
    return ConversationMessage(
        role=role,
        content=content,
        metadata=metadata or {},
    )
