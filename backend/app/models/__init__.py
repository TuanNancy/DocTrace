"""
Models package for RAG PDF Chatbot.

This package contains all data models for documents, chunks, queries,
conversations, and agent tasks.
"""

# ==================== Document Models ====================
from app.models.document import (
    # Enums
    DocumentStatus,
    QueryMode,
    TaskStatus,
    # Dataclasses
    DocumentChunk,
    Document,
    RetrievedChunk,
    QueryResult,
    IndexingResult,
    # Pydantic Models
    DocumentChunkResponse,
    DocumentResponse,
    QueryResponse,
    # Factory Functions
    create_document_chunk,
    create_retrieved_chunk,
    create_query_result,
)

# ==================== Conversation Models ====================
from app.models.agent import (
    # Enums
    MessageRole,
    ConversationState,
    # Dataclasses
    ConversationMessage,
    ConversationSummary,
    ConversationContext,
    # Pydantic Models
    ConversationMessageResponse,
    # Factory Functions
    create_conversation_message,
)

# ==================== Exports ====================
__all__ = [
    # Document Enums
    "DocumentStatus",
    "QueryMode",
    "TaskStatus",
    # Document Dataclasses
    "DocumentChunk",
    "Document",
    "RetrievedChunk",
    "QueryResult",
    "IndexingResult",
    # Document Pydantic Models
    "DocumentChunkResponse",
    "DocumentResponse",
    "QueryResponse",
    # Document Factory Functions
    "create_document_chunk",
    "create_retrieved_chunk",
    "create_query_result",
    # Conversation Enums
    "MessageRole",
    "ConversationState",
    # Conversation Dataclasses
    "ConversationMessage",
    "ConversationSummary",
    "ConversationContext",
    # Conversation Pydantic Models
    "ConversationMessageResponse",
    # Conversation Factory Functions
    "create_conversation_message",
]
