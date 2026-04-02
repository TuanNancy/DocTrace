"""
RAG Agent for document query processing.

This module implements the main RAG agent that orchestrates document retrieval,
context processing, and response synthesis. It follows the DocPixie architecture
but is adapted for embeddings/vector databases instead of vision AI.
"""
import logging
import time
from datetime import datetime
from typing import AsyncIterator, Dict, List, Optional, Any

from app.ai.prompts import PromptTemplates, format_response_synthesizer
from app.core.config import get_config
from app.models.agent import (
    ConversationMessage,
    ConversationContext,
    ConversationSummary,
    MessageRole,
    create_conversation_message,
)
from app.models.document import (
    QueryResult,
    QueryMode,
    RetrievedChunk,
    create_query_result,
)
from app.providers.base import BaseProvider
from app.providers.embeddings import get_embedder
from app.storage.base import BaseStorage, RetrievedChunk as StorageRetrievedChunk

logger = logging.getLogger(__name__)


class RAGAgent:
    """
    Main RAG agent for document query processing.

    This agent orchestrates the complete RAG workflow:
    1. Context processing (conversation summarization if needed)
    2. Query reformulation (reference resolution)
    3. Vector search and retrieval
    4. Response synthesis with citations

    The agent is provider-agnostic and can work with different LLM providers
    and vector databases through the factory pattern.
    """

    def __init__(
        self,
        provider: Optional[BaseProvider] = None,
        storage: Optional[BaseStorage] = None,
        config: Optional[Any] = None,
    ):
        """
        Initialize the RAG agent.

        Args:
            provider: LLM provider instance (created from config if not provided)
            storage: Storage backend instance (created from config if not provided)
            config: Configuration instance (uses global config if not provided)
        """
        self.config = config or get_config()
        self.provider = provider
        self.storage = storage
        self.embedder = get_embedder()

        # Conversation history
        self.conversation_history: List[ConversationMessage] = []
        self.conversation_id: Optional[str] = None

        # Statistics
        self.total_queries = 0
        self.total_cost = 0.0
        # Filled after each `process_query_stream` (RAG path) for API layers (e.g. SSE sources)
        self._last_stream_retrieved_chunks: List[StorageRetrievedChunk] = []

    async def initialize(self) -> None:
        """
        Initialize the agent and its dependencies.

        Creates provider and storage instances if not provided,
        and connects to the storage backend.
        """
        # Create provider if not provided
        if self.provider is None:
            from app.providers.factory import create_provider
            self.provider = create_provider(
                provider=self.config.provider,
                model=self.config.model,
            )
            logger.info(f"Created provider: {self.config.provider}")

        # Create storage if not provided
        if self.storage is None:
            from app.storage.factory import create_storage
            self.storage = create_storage(
                storage_type=self.config.storage_type,
            )
            logger.info(f"Created storage: {self.config.storage_type}")

        # Connect to storage
        await self.storage.connect()
        logger.info("RAG Agent initialized successfully")

    async def shutdown(self) -> None:
        """Shutdown the agent and cleanup resources."""
        if self.storage:
            await self.storage.disconnect()
        logger.info("RAG Agent shutdown complete")

    async def process_query(
        self,
        query: str,
        doc_id: Optional[str] = None,
        mode: QueryMode = QueryMode.AUTO,
        language: str = "vi",
        stream: bool = False,
    ) -> QueryResult:
        """
        Process a query using RAG workflow.

        Args:
            query: User query
            doc_id: Optional document ID to search within
            mode: Query processing mode (AUTO, RAG, DIRECT)
            language: Language for prompts and responses ("vi" or "en")
            stream: Whether to stream the response (not yet implemented)

        Returns:
            QueryResult with answer and metadata
        """
        start_time = time.time()

        try:
            # Determine if we need document retrieval
            if mode == QueryMode.AUTO:
                needs_retrieval = await self._classify_query(query, language)
                mode = QueryMode.RAG if needs_retrieval else QueryMode.DIRECT
            else:
                needs_retrieval = mode == QueryMode.RAG

            # Process based on mode
            if needs_retrieval:
                result = await self._process_rag_query(query, doc_id, language, start_time)
            else:
                result = await self._process_direct_query(query, language, start_time)

            # Update conversation history
            self._add_to_conversation(MessageRole.USER, query)
            self._add_to_conversation(MessageRole.ASSISTANT, result.answer)

            # Update statistics
            self.total_queries += 1
            self.total_cost += result.total_cost

            return result

        except Exception as e:
            logger.exception(f"Error processing query: {e}")
            # Return error result
            processing_time = time.time() - start_time
            return create_query_result(
                query=query,
                answer=f"Error processing query: {str(e)}",
                retrieved_chunks=[],
                mode=mode,
                processing_time=processing_time,
            )

    async def process_query_stream(
        self,
        query: str,
        doc_id: Optional[str] = None,
        mode: QueryMode = QueryMode.AUTO,
        language: str = "vi",
        *,
        retrieved_chunks_override: Optional[List[StorageRetrievedChunk]] = None,
    ) -> AsyncIterator[str]:
        """
        Process a query and stream the response.

        Args:
            query: User query
            doc_id: Optional document ID to search within
            mode: Query processing mode (AUTO, RAG, DIRECT)
            language: Language for prompts and responses ("vi" or "en")
            retrieved_chunks_override: If set (RAG mode), skip retrieval and use these chunks

        Yields:
            Response tokens as they arrive
        """
        start_time = time.time()
        self._last_stream_retrieved_chunks = []

        try:
            # Determine if we need document retrieval
            if mode == QueryMode.AUTO:
                needs_retrieval = await self._classify_query(query, language)
                mode = QueryMode.RAG if needs_retrieval else QueryMode.DIRECT
            else:
                needs_retrieval = mode == QueryMode.RAG

            if needs_retrieval:
                # RAG mode: retrieve chunks first (or use pre-fetched list from router)
                retrieved_chunks = (
                    retrieved_chunks_override
                    if retrieved_chunks_override is not None
                    else await self._retrieve_chunks(query, doc_id)
                )
                self._last_stream_retrieved_chunks = list(retrieved_chunks)
                context = self._build_context(retrieved_chunks)

                # Stream LLM response with retrieved context (OpenRouter chat completions)
                system_prompt = PromptTemplates.get_system_prompt(language)

                tokens = []
                async for token in self.provider.stream_with_context(
                    query=query,
                    context=context,
                    system_prompt=system_prompt,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                ):
                    tokens.append(token)
                    yield token

                answer = "".join(tokens)

            else:
                # Direct mode: stream without retrieval
                tokens = []
                async for token in self.provider.stream_text_messages(
                    messages=[{"role": "user", "content": query}],
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                ):
                    tokens.append(token)
                    yield token

                answer = "".join(tokens)

            # Update conversation history
            self._add_to_conversation(MessageRole.USER, query)
            self._add_to_conversation(MessageRole.ASSISTANT, answer)

            # Update statistics
            self.total_queries += 1

        except Exception as e:
            logger.exception(f"Error in streaming query: {e}")
            yield f"Error: {str(e)}"

    async def _classify_query(self, query: str, language: str) -> bool:
        """
        Classify whether a query needs document retrieval.

        Args:
            query: User query
            language: Language for prompts

        Returns:
            True if retrieval is needed, False otherwise
        """
        # Simple heuristic: if query is very short or generic, might not need retrieval
        # In a more sophisticated implementation, this would use an LLM classifier
        generic_keywords = ["hello", "hi", "thanks", "thank you", "bye", "goodbye"]
        query_lower = query.lower().strip()

        # Check for greetings
        if any(keyword in query_lower for keyword in generic_keywords):
            return False

        # Check for very short queries (less than 3 words)
        if len(query_lower.split()) < 3:
            return False

        # Default to needing retrieval for document-specific queries
        return True

    async def _process_rag_query(
        self,
        query: str,
        doc_id: Optional[str],
        language: str,
        start_time: float,
    ) -> QueryResult:
        """
        Process a query with RAG retrieval.

        Args:
            query: User query
            doc_id: Optional document ID
            language: Language for prompts
            start_time: Query start time

        Returns:
            QueryResult with answer and retrieved chunks
        """
        # Retrieve relevant chunks
        retrieved_chunks = await self._retrieve_chunks(query, doc_id)

        if not retrieved_chunks:
            # No chunks found
            processing_time = time.time() - start_time
            return create_query_result(
                query=query,
                answer="Không tìm thấy nội dung liên quan trong tài liệu." if language == "vi" else "No relevant content found in the document.",
                retrieved_chunks=[],
                mode=QueryMode.RAG,
                processing_time=processing_time,
            )

        # Build context
        context = self._build_context(retrieved_chunks)

        # Generate response
        system_prompt = PromptTemplates.get_system_prompt(language)
        answer = await self.provider.process_with_context(
            query=query,
            context=context,
            system_prompt=system_prompt,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

        processing_time = time.time() - start_time

        # Convert storage chunks to model chunks
        model_chunks = [
            RetrievedChunk(
                chunk_id=chunk.chunk_id,
                doc_id=chunk.doc_id,
                text=chunk.text,
                page=chunk.page,
                source=chunk.source,
                score=chunk.score,
                metadata=chunk.metadata,
            )
            for chunk in retrieved_chunks
        ]

        return create_query_result(
            query=query,
            answer=answer,
            retrieved_chunks=model_chunks,
            mode=QueryMode.RAG,
            processing_time=processing_time,
        )

    async def _process_direct_query(
        self,
        query: str,
        language: str,
        start_time: float,
    ) -> QueryResult:
        """
        Process a query without document retrieval.

        Args:
            query: User query
            language: Language for prompts
            start_time: Query start time

        Returns:
            QueryResult with direct answer
        """
        # Generate direct response
        answer = await self.provider.process_text_messages(
            messages=[{"role": "user", "content": query}],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

        processing_time = time.time() - start_time

        return create_query_result(
            query=query,
            answer=answer,
            retrieved_chunks=[],
            mode=QueryMode.DIRECT,
            processing_time=processing_time,
        )

    async def _retrieve_chunks(
        self,
        query: str,
        doc_id: Optional[str] = None,
    ) -> List[StorageRetrievedChunk]:
        """
        Retrieve relevant chunks using vector search.

        Args:
            query: User query
            doc_id: Optional document ID to filter results

        Returns:
            List of retrieved chunks
        """
        # Embed query
        query_vectors = self.embedder.embed_documents([query])
        if not query_vectors:
            logger.warning("Failed to embed query")
            return []

        query_vector = query_vectors[0]

        # Search in storage
        retrieved_chunks = await self.storage.search_chunks(
            query_vector=query_vector,
            doc_id=doc_id,
            top_k=self.config.retrieval_top_k,
            min_score=self.config.min_relevance_score,
        )

        logger.info(f"Retrieved {len(retrieved_chunks)} chunks for query: {query[:50]}...")
        return retrieved_chunks

    def _build_context(self, chunks: List[StorageRetrievedChunk]) -> str:
        """
        Build context string from retrieved chunks.

        Args:
            chunks: List of retrieved chunks

        Returns:
            Formatted context string
        """
        if not chunks:
            return ""

        parts = []
        total_chars = 0
        max_chars = self.config.context_max_chars

        for chunk in chunks:
            # Format chunk with page and score
            block = f"[Trang {chunk.page}] (độ liên quan: {chunk.score:.2f})\n{chunk.text}"

            if total_chars + len(block) > max_chars and parts:
                break

            parts.append(block)
            total_chars += len(block)

        return "\n\n---\n\n".join(parts) if parts else ""

    def _add_to_conversation(self, role: MessageRole, content: str) -> None:
        """
        Add a message to conversation history.

        Args:
            role: Message role
            content: Message content
        """
        message = create_conversation_message(
            role=role,
            content=content,
        )
        self.conversation_history.append(message)

        # Manage conversation size
        if len(self.conversation_history) > self.config.max_conversation_turns * 2:
            # Keep recent messages and summarize older ones
            self._manage_conversation_size()

    def _manage_conversation_size(self) -> None:
        """
        Manage conversation size by summarizing old messages.

        Keeps the most recent messages and summarizes older ones to
        maintain context while managing token usage.
        """
        if len(self.conversation_history) <= self.config.max_conversation_turns * 2:
            return

        # Keep recent messages
        keep_count = self.config.turns_to_keep_full * 2
        recent_messages = self.conversation_history[-keep_count:]
        older_messages = self.conversation_history[:-keep_count]

        # In a more sophisticated implementation, we would summarize older messages
        # For now, just keep the recent messages
        self.conversation_history = recent_messages

        logger.info(f"Managed conversation size: kept {len(self.conversation_history)} messages")

    async def get_conversation_context(self) -> ConversationContext:
        """
        Get the current conversation context.

        Returns:
            ConversationContext with recent messages and summary
        """
        return ConversationContext(
            conversation_id=self.conversation_id or "default",
            recent_messages=self.conversation_history,
            summary=None,  # Summary not implemented yet
            total_message_count=len(self.conversation_history),
            processed_at=datetime.utcnow(),
        )

    def clear_conversation(self) -> None:
        """Clear the conversation history."""
        self.conversation_history.clear()
        self.conversation_id = None
        logger.info("Conversation cleared")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get agent statistics.

        Returns:
            Dictionary with agent statistics
        """
        return {
            "total_queries": self.total_queries,
            "total_cost": round(self.total_cost, 6),
            "conversation_length": len(self.conversation_history),
            "provider": self.provider.get_model_info() if self.provider else None,
        }

    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on the agent and its dependencies.

        Returns:
            Dictionary with health status
        """
        health = {
            "status": "healthy",
            "provider_connected": False,
            "storage_connected": False,
        }

        # Check provider
        if self.provider:
            try:
                health["provider_connected"] = self.provider.validate_api_key()
                health["provider_info"] = self.provider.get_model_info()
            except Exception as e:
                health["status"] = "unhealthy"
                health["provider_error"] = str(e)

        # Check storage
        if self.storage:
            try:
                storage_health = await self.storage.health_check()
                health["storage_connected"] = storage_health.get("connected", False)
                health["storage_info"] = storage_health
            except Exception as e:
                health["status"] = "unhealthy"
                health["storage_error"] = str(e)

        return health


# ==================== Factory Functions ====================

async def create_rag_agent(
    provider: Optional[BaseProvider] = None,
    storage: Optional[BaseStorage] = None,
    config: Optional[Any] = None,
) -> RAGAgent:
    """
    Create and initialize a RAG agent.

    Args:
        provider: Optional LLM provider instance
        storage: Optional storage backend instance
        config: Optional configuration instance

    Returns:
        Initialized RAGAgent instance

    Example:
        >>> agent = await create_rag_agent()
        >>> result = await agent.process_query("What is the main topic?")
        >>> await agent.shutdown()
    """
    agent = RAGAgent(
        provider=provider,
        storage=storage,
        config=config,
    )
    await agent.initialize()
    return agent


async def create_rag_agent_with_defaults() -> RAGAgent:
    """
    Create a RAG agent with default configuration.

    This is a convenience function that creates a RAG agent using
    the global configuration.

    Returns:
        Initialized RAGAgent instance

    Example:
        >>> agent = await create_rag_agent_with_defaults()
        >>> result = await agent.process_query("What is the main topic?")
        >>> await agent.shutdown()
    """
    return await create_rag_agent()
