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

# ==================== Agent Models ====================
from app.models.agent import (
    # Enums
    MessageRole,
    TaskType,
    ConversationState,
    # Dataclasses
    ConversationMessage,
    ConversationSummary,
    ConversationContext,
    AgentTask,
    TaskPlan,
    TaskResult,
    AgentQueryResult,
    # Pydantic Models
    ConversationMessageResponse,
    AgentTaskResponse,
    TaskPlanResponse,
    # Factory Functions
    create_conversation_message,
    create_agent_task,
    create_task_plan,
    create_task_result,
    create_agent_query_result,
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
    # Agent Enums
    "MessageRole",
    "TaskType",
    "ConversationState",
    # Agent Dataclasses
    "ConversationMessage",
    "ConversationSummary",
    "ConversationContext",
    "AgentTask",
    "TaskPlan",
    "TaskResult",
    "AgentQueryResult",
    # Agent Pydantic Models
    "ConversationMessageResponse",
    "AgentTaskResponse",
    "TaskPlanResponse",
    # Agent Factory Functions
    "create_conversation_message",
    "create_agent_task",
    "create_task_plan",
    "create_task_result",
    "create_agent_query_result",
]
