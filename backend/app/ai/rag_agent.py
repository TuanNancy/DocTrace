"""
RAG Agent for document query processing.
Orchestrates document retrieval, context building, and streaming LLM responses.
"""
import logging
from typing import AsyncIterator, List, Optional, Any

from app.ai.prompts import PromptTemplates
from app.core.config import get_config
from app.providers.base import BaseProvider
from app.providers.embeddings import get_embedder
from app.storage.base import BaseStorage, RetrievedChunk as StorageRetrievedChunk

logger = logging.getLogger(__name__)


class RAGAgent:
    def __init__(
        self,
        provider: Optional[BaseProvider] = None,
        storage: Optional[BaseStorage] = None,
        config: Optional[Any] = None,
    ):
        self.config = config or get_config()
        self.provider = provider
        self.storage = storage
        self.embedder = get_embedder()

    async def initialize(self) -> None:
        if self.provider is None:
            from app.providers.factory import create_provider
            self.provider = create_provider(model=self.config.model)
            logger.info("Created OpenRouter provider")

        if self.storage is None:
            from app.storage.factory import create_storage
            self.storage = create_storage(storage_type=self.config.storage_type)
            logger.info("Created Milvus storage")

        await self.storage.connect()
        logger.info("RAG Agent initialized successfully")

    async def shutdown(self) -> None:
        if self.storage:
            await self.storage.disconnect()
        logger.info("RAG Agent shutdown complete")

    async def _retrieve_chunks(
        self,
        query: str,
        doc_id: Optional[str] = None,
    ) -> List[StorageRetrievedChunk]:
        query_vectors = self.embedder.embed_documents([query])
        if not query_vectors:
            logger.warning("Failed to embed query")
            return []

        query_vector = query_vectors[0]

        retrieved_chunks = await self.storage.search_chunks(
            query_vector=query_vector,
            doc_id=doc_id,
            top_k=self.config.retrieval_top_k,
            min_score=self.config.min_relevance_score,
        )

        logger.info(f"Retrieved {len(retrieved_chunks)} chunks for query: {query[:50]}...")
        return retrieved_chunks

    def _build_context(self, chunks: List[StorageRetrievedChunk]) -> str:
        if not chunks:
            return ""

        parts = []
        total_chars = 0
        max_chars = self.config.context_max_chars

        for chunk in chunks:
            block = f"[Trang {chunk.page}] (độ liên quan: {chunk.score:.2f})\n{chunk.text}"

            if total_chars + len(block) > max_chars and parts:
                break

            parts.append(block)
            total_chars += len(block)

        return "\n\n---\n\n".join(parts) if parts else ""

    async def process_query_stream(
        self,
        query: str,
        doc_id: Optional[str] = None,
        language: str = "vi",
        *,
        retrieved_chunks_override: Optional[List[StorageRetrievedChunk]] = None,
    ) -> AsyncIterator[str]:
        try:
            retrieved_chunks = (
                retrieved_chunks_override
                if retrieved_chunks_override is not None
                else await self._retrieve_chunks(query, doc_id)
            )

            if not retrieved_chunks:
                fallback = (
                    "Không tìm thấy đoạn văn nào trong tài liệu đủ liên quan với câu hỏi. "
                    "Hãy thử đặt câu hỏi gần với nội dung file hơn."
                    if language == "vi"
                    else "No sufficiently relevant passages were retrieved from this document."
                )
                yield fallback
                return

            context = self._build_context(retrieved_chunks)
            system_prompt = PromptTemplates.get_system_prompt(language)

            async for token in self.provider.stream_with_context(
                query=query,
                context=context,
                system_prompt=system_prompt,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            ):
                yield token

        except Exception as e:
            logger.exception(f"Error in streaming query: {e}")
            yield f"Error: {str(e)}"


async def create_rag_agent_with_defaults() -> RAGAgent:
    agent = RAGAgent()
    await agent.initialize()
    return agent
