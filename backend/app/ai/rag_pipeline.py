"""
RAG pipeline for document question answering.
Orchestrates document retrieval, context building, and streaming LLM responses.
"""
import logging
from typing import AsyncIterator, List, Optional

from app.ai.prompts import PromptTemplates
from app.core.config import AppConfig, get_config
from app.providers.base import ChatProvider
from app.providers.embeddings import get_embedder
from app.storage.base import VectorStore, RetrievedChunk

logger = logging.getLogger(__name__)


class RAGPipeline:
    def __init__(
        self,
        chat_provider: Optional[ChatProvider] = None,
        vector_store: Optional[VectorStore] = None,
        config: Optional[AppConfig] = None,
    ):
        self.config = config or get_config()
        self.chat_provider = chat_provider
        self.vector_store = vector_store
        self.embedder = get_embedder()

    async def initialize(self) -> None:
        if self.chat_provider is None:
            from app.providers.factory import create_chat_provider
            self.chat_provider = create_chat_provider(model=self.config.model)
            logger.info("Created OpenRouter chat provider")

        if self.vector_store is None:
            from app.storage.factory import create_vector_store
            self.vector_store = create_vector_store(vector_store_type=self.config.vector_store_type)
            logger.info("Created Milvus vector store")

        await self.vector_store.connect()
        logger.info("RAG pipeline initialized successfully")

    async def shutdown(self) -> None:
        if self.vector_store:
            await self.vector_store.disconnect()
        logger.info("RAG pipeline shutdown complete")

    async def retrieve_chunks(
        self,
        query: str,
        doc_id: Optional[str] = None,
    ) -> List[RetrievedChunk]:
        query_vectors = self.embedder.embed_documents([query])
        if not query_vectors:
            logger.warning("Failed to embed query")
            return []

        query_vector = query_vectors[0]

        retrieved_chunks = await self.vector_store.search_chunks(
            query_vector=query_vector,
            doc_id=doc_id,
            top_k=self.config.retrieval_top_k,
            min_score=self.config.min_relevance_score,
        )

        logger.info(f"Retrieved {len(retrieved_chunks)} chunks for query: {query[:50]}...")
        return retrieved_chunks

    def _build_context(self, chunks: List[RetrievedChunk]) -> str:
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

    async def stream_answer(
        self,
        query: str,
        doc_id: Optional[str] = None,
        language: str = "vi",
        *,
        retrieved_chunks_override: Optional[List[RetrievedChunk]] = None,
    ) -> AsyncIterator[str]:
        try:
            retrieved_chunks = (
                retrieved_chunks_override
                if retrieved_chunks_override is not None
                else await self.retrieve_chunks(query, doc_id)
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

            async for text_delta in self.chat_provider.stream_with_context(
                query=query,
                context=context,
                system_prompt=system_prompt,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            ):
                yield text_delta

        except Exception as e:
            logger.exception(f"Error in streaming query: {e}")
            yield f"Error: {str(e)}"


async def create_initialized_rag_pipeline() -> RAGPipeline:
    """Create a pipeline and connect its vector store; the caller must shut it down."""
    pipeline = RAGPipeline()
    await pipeline.initialize()
    return pipeline
