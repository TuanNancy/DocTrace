"""
Agent models for conversation and task management.
Defines the core data models for agent-based query processing and conversation tracking.
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


class TaskType(str, Enum):
    """Type of agent task."""
    RETRIEVAL = "retrieval"  # Retrieve relevant chunks
    ANALYSIS = "analysis"    # Analyze retrieved content
    SYNTHESIS = "synthesis"  # Synthesize final answer
    REFORMULATION = "reformulation"  # Reformulate query with context


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


# ==================== Agent Task Models ====================

@dataclass
class AgentTask:
    """
    Represents a single task in an agent's execution plan.

    Each task has a specific type, description, and status for
    tracking the agent's workflow.
    """
    task_id: str
    task_type: TaskType
    name: str
    description: str
    status: TaskStatus
    document_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary."""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "document_id": self.document_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "metadata": self.metadata,
        }

    @property
    def is_pending(self) -> bool:
        """Check if task is pending."""
        return self.status == TaskStatus.PENDING

    @property
    def is_in_progress(self) -> bool:
        """Check if task is in progress."""
        return self.status == TaskStatus.IN_PROGRESS

    @property
    def is_completed(self) -> bool:
        """Check if task is completed."""
        return self.status == TaskStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        """Check if task has failed."""
        return self.status == TaskStatus.FAILED


@dataclass
class TaskPlan:
    """
    Represents a plan of tasks for agent execution.

    Contains the initial query, list of tasks, and iteration
    information for adaptive task planning.
    """
    plan_id: str
    initial_query: str
    tasks: List[AgentTask]
    current_iteration: int
    max_iterations: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert plan to dictionary."""
        return {
            "plan_id": self.plan_id,
            "initial_query": self.initial_query,
            "tasks": [t.to_dict() for t in self.tasks],
            "current_iteration": self.current_iteration,
            "max_iterations": self.max_iterations,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "metadata": self.metadata,
        }

    def get_pending_tasks(self) -> List[AgentTask]:
        """Get all pending tasks."""
        return [t for t in self.tasks if t.is_pending]

    def get_in_progress_tasks(self) -> List[AgentTask]:
        """Get all in-progress tasks."""
        return [t for t in self.tasks if t.is_in_progress]

    def get_completed_tasks(self) -> List[AgentTask]:
        """Get all completed tasks."""
        return [t for t in self.tasks if t.is_completed]

    def get_failed_tasks(self) -> List[AgentTask]:
        """Get all failed tasks."""
        return [t for t in self.tasks if t.is_failed]

    @property
    def is_complete(self) -> bool:
        """Check if all tasks are completed."""
        return all(t.is_completed or t.is_failed for t in self.tasks)

    @property
    def has_pending_tasks(self) -> bool:
        """Check if there are pending tasks."""
        return len(self.get_pending_tasks()) > 0

    @property
    def progress(self) -> float:
        """Get progress percentage (0.0 to 1.0)."""
        if not self.tasks:
            return 0.0
        completed = len(self.get_completed_tasks())
        return completed / len(self.tasks)


@dataclass
class TaskResult:
    """
    Represents the result of executing a single task.

    Contains the task, retrieved chunks, analysis, and metadata
    about the task execution.
    """
    task: AgentTask
    retrieved_chunks: List[Any]  # RetrievedChunk instances
    analysis: str
    pages_analyzed: int
    processing_time: float
    created_at: datetime
    cost: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert task result to dictionary."""
        return {
            "task": self.task.to_dict(),
            "retrieved_chunks": [c.to_dict() if hasattr(c, 'to_dict') else c for c in self.retrieved_chunks],
            "analysis": self.analysis,
            "pages_analyzed": self.pages_analyzed,
            "processing_time": round(self.processing_time, 3),
            "created_at": self.created_at.isoformat(),
            "cost": round(self.cost, 6),
            "metadata": self.metadata,
        }

    def get_sources(self) -> List[str]:
        """Get unique sources from retrieved chunks."""
        sources = set()
        for chunk in self.retrieved_chunks:
            if hasattr(chunk, 'source'):
                sources.add(chunk.source)
        return list(sources)

    def get_pages(self) -> List[int]:
        """Get unique page numbers from retrieved chunks."""
        pages = set()
        for chunk in self.retrieved_chunks:
            if hasattr(chunk, 'page'):
                pages.add(chunk.page)
        return sorted(pages)


@dataclass
class AgentQueryResult:
    """
    Represents the result of an agent-based query execution.

    Contains the query, answer, all task results, and metadata
    about the agent's execution.
    """
    query: str
    answer: str
    task_results: List[TaskResult]
    total_iterations: int
    processing_time_seconds: float
    created_at: datetime
    total_cost: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert agent query result to dictionary."""
        return {
            "query": self.query,
            "answer": self.answer,
            "task_results": [tr.to_dict() for tr in self.task_results],
            "total_iterations": self.total_iterations,
            "processing_time_seconds": round(self.processing_time_seconds, 3),
            "created_at": self.created_at.isoformat(),
            "total_cost": round(self.total_cost, 6),
            "metadata": self.metadata,
        }

    def get_all_retrieved_chunks(self) -> List[Any]:
        """Get all retrieved chunks from all tasks."""
        all_chunks = []
        for result in self.task_results:
            all_chunks.extend(result.retrieved_chunks)
        return all_chunks

    def get_all_sources(self) -> List[str]:
        """Get all unique sources from all tasks."""
        sources = set()
        for result in self.task_results:
            sources.update(result.get_sources())
        return list(sources)

    def get_all_pages(self) -> List[int]:
        """Get all unique page numbers from all tasks."""
        pages = set()
        for result in self.task_results:
            pages.update(result.get_pages())
        return sorted(pages)

    def get_task_summary(self) -> str:
        """Get a summary of task execution."""
        completed = sum(1 for tr in self.task_results if tr.task.is_completed)
        failed = sum(1 for tr in self.task_results if tr.task.is_failed)
        total_chunks = sum(len(tr.retrieved_chunks) for tr in self.task_results)

        return (
            f"Executed {len(self.task_results)} tasks: "
            f"{completed} completed, {failed} failed. "
            f"Retrieved {total_chunks} chunks total."
        )


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


class AgentTaskResponse(BaseModel):
    """Pydantic model for agent task API responses."""
    task_id: str = Field(..., description="Unique task identifier")
    task_type: str = Field(..., description="Task type (retrieval, analysis, synthesis)")
    name: str = Field(..., description="Task name")
    description: str = Field(..., description="Task description")
    status: str = Field(..., description="Task status")
    document_id: Optional[str] = Field(None, description="Associated document ID")

    class Config:
        json_schema_extra = {
            "example": {
                "task_id": "task-5678",
                "task_type": "retrieval",
                "name": "Retrieve relevant chunks",
                "description": "Search for chunks related to the query",
                "status": "completed",
                "document_id": "doc-1234",
            }
        }


class TaskPlanResponse(BaseModel):
    """Pydantic model for task plan API responses."""
    plan_id: str = Field(..., description="Unique plan identifier")
    initial_query: str = Field(..., description="Initial query that generated the plan")
    tasks: List[AgentTaskResponse] = Field(..., description="List of tasks in the plan")
    current_iteration: int = Field(..., description="Current iteration number")
    max_iterations: int = Field(..., description="Maximum iterations allowed")
    progress: float = Field(..., description="Progress percentage (0.0 to 1.0)")

    class Config:
        json_schema_extra = {
            "example": {
                "plan_id": "plan-9012",
                "initial_query": "What are the key benefits?",
                "tasks": [],
                "current_iteration": 1,
                "max_iterations": 5,
                "progress": 0.5,
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


def create_agent_task(
    task_type: TaskType,
    name: str,
    description: str,
    document_id: Optional[str] = None,
    task_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> AgentTask:
    """
    Factory function to create an AgentTask.

    Args:
        task_type: Type of task
        name: Task name
        description: Task description
        document_id: Optional document ID
        task_id: Optional task ID (generated if not provided)
        metadata: Optional metadata dictionary

    Returns:
        AgentTask instance
    """
    import uuid
    from app.models.document import TaskStatus

    return AgentTask(
        task_id=task_id or str(uuid.uuid4()),
        task_type=task_type,
        name=name,
        description=description,
        status=TaskStatus.PENDING,
        document_id=document_id,
        created_at=datetime.utcnow(),
        metadata=metadata or {},
    )


def create_task_plan(
    initial_query: str,
    tasks: List[AgentTask],
    max_iterations: int = 5,
    plan_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> TaskPlan:
    """
    Factory function to create a TaskPlan.

    Args:
        initial_query: Initial query that generated the plan
        tasks: List of tasks in the plan
        max_iterations: Maximum iterations allowed
        plan_id: Optional plan ID (generated if not provided)
        metadata: Optional metadata dictionary

    Returns:
        TaskPlan instance
    """
    import uuid

    return TaskPlan(
        plan_id=plan_id or str(uuid.uuid4()),
        initial_query=initial_query,
        tasks=tasks,
        current_iteration=1,
        max_iterations=max_iterations,
        created_at=datetime.utcnow(),
        metadata=metadata or {},
    )


def create_task_result(
    task: AgentTask,
    retrieved_chunks: List[Any],
    analysis: str,
    processing_time: float,
    cost: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None
) -> TaskResult:
    """
    Factory function to create a TaskResult.

    Args:
        task: The task that was executed
        retrieved_chunks: List of retrieved chunks
        analysis: Analysis of the retrieved content
        processing_time: Processing time in seconds
        cost: Cost of task execution
        metadata: Optional metadata dictionary

    Returns:
        TaskResult instance
    """
    pages_analyzed = len(set(c.page for c in retrieved_chunks if hasattr(c, 'page')))

    return TaskResult(
        task=task,
        retrieved_chunks=retrieved_chunks,
        analysis=analysis,
        pages_analyzed=pages_analyzed,
        processing_time=processing_time,
        created_at=datetime.utcnow(),
        cost=cost,
        metadata=metadata or {},
    )


def create_agent_query_result(
    query: str,
    answer: str,
    task_results: List[TaskResult],
    processing_time_seconds: float,
    total_cost: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None
) -> AgentQueryResult:
    """
    Factory function to create an AgentQueryResult.

    Args:
        query: Original query
        answer: Generated answer
        task_results: List of task execution results
        processing_time_seconds: Total processing time in seconds
        total_cost: Total cost of execution
        metadata: Optional metadata dictionary

    Returns:
        AgentQueryResult instance
    """
    return AgentQueryResult(
        query=query,
        answer=answer,
        task_results=task_results,
        total_iterations=len(task_results),
        processing_time_seconds=processing_time_seconds,
        created_at=datetime.utcnow(),
        total_cost=total_cost,
        metadata=metadata or {},
    )
