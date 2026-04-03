"""
Models package for RAG PDF Chatbot.
"""

from app.models.document import (
    DocumentStatus,
    QueryMode,
    RetrievedChunk,
    QueryResult,
    IndexingResult,
    create_query_result,
    create_indexing_result,
)

from app.models.agent import (
    MessageRole,
    ConversationMessage,
    ConversationSummary,
    ConversationContext,
    create_conversation_message,
)

__all__ = [
    "DocumentStatus",
    "QueryMode",
    "RetrievedChunk",
    "QueryResult",
    "IndexingResult",
    "create_query_result",
    "create_indexing_result",
    "MessageRole",
    "ConversationMessage",
    "ConversationSummary",
    "ConversationContext",
    "create_conversation_message",
]
