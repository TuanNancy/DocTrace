"""
Base storage interface for vector database operations.
Defines the contract that all storage backends must implement.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class DocumentMetadata:
    """Metadata for a stored document."""
    doc_id: str
    name: str
    chunks_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    status: str = "completed"  # pending, processing, completed, failed
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class RetrievedChunk:
    """A chunk retrieved from vector search."""
    chunk_id: str
    doc_id: str
    text: str
    page: int
    source: str
    score: float
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class InsertResult:
    """Result of inserting chunks into storage."""
    doc_id: str
    chunks_inserted: int
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class BaseStorage(ABC):
    """
    Abstract base class for storage backends.

    All storage backends must implement these methods to ensure consistent
    interaction with different vector databases (Milvus, Chroma, etc.).
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the storage backend.

        Args:
            config: Configuration dictionary for the storage backend
        """
        self.config = config
        self._connected = False

    @abstractmethod
    async def connect(self) -> None:
        """
        Establish connection to the storage backend.

        This method should handle all connection setup logic.
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Close connection to the storage backend.

        This method should handle all connection cleanup logic.
        """
        pass

    @abstractmethod
    async def is_connected(self) -> bool:
        """
        Check if the storage backend is connected.

        Returns:
            True if connected, False otherwise
        """
        pass

    @abstractmethod
    async def ensure_collection(
        self,
        vector_dim: int,
        recreate: bool = False
    ) -> None:
        """
        Ensure that the collection exists and is properly configured.

        Args:
            vector_dim: Dimension of the vectors to be stored
            recreate: If True, drop and recreate the collection
        """
        pass

    @abstractmethod
    async def insert_chunks(
        self,
        doc_id: str,
        chunks: List[Dict[str, Any]],
        vectors: List[List[float]],
        batch_size: int = 64
    ) -> InsertResult:
        """
        Insert document chunks with their embeddings into storage.

        Args:
            doc_id: Unique document identifier
            chunks: List of chunk dictionaries with keys: text, page, source
            vectors: List of embedding vectors corresponding to chunks
            batch_size: Number of chunks to insert per batch

        Returns:
            InsertResult with doc_id, chunks_inserted, and warnings
        """
        pass

    @abstractmethod
    async def search_chunks(
        self,
        query_vector: List[float],
        doc_id: Optional[str] = None,
        top_k: int = 8,
        min_score: Optional[float] = None
    ) -> List[RetrievedChunk]:
        """
        Search for similar chunks using vector similarity.

        Args:
            query_vector: Query embedding vector
            doc_id: Optional document ID to filter results
            top_k: Maximum number of results to return
            min_score: Minimum relevance score threshold

        Returns:
            List of RetrievedChunk objects sorted by relevance
        """
        pass

    @abstractmethod
    async def get_document_metadata(
        self,
        doc_id: str
    ) -> Optional[DocumentMetadata]:
        """
        Get metadata for a specific document.

        Args:
            doc_id: Document identifier

        Returns:
            DocumentMetadata or None if not found
        """
        pass

    @abstractmethod
    async def list_documents(
        self,
        limit: int = 100,
        offset: int = 0
    ) -> List[DocumentMetadata]:
        """
        List all documents in storage.

        Args:
            limit: Maximum number of documents to return
            offset: Number of documents to skip

        Returns:
            List of DocumentMetadata objects
        """
        pass

    @abstractmethod
    async def delete_document(
        self,
        doc_id: str
    ) -> bool:
        """
        Delete a document and all its chunks from storage.

        Args:
            doc_id: Document identifier

        Returns:
            True if deleted successfully, False otherwise
        """
        pass

    @abstractmethod
    async def search_documents(
        self,
        query: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search for documents by metadata (not vector search).

        Args:
            query: Search query string
            limit: Maximum number of results

        Returns:
            List of document metadata dictionaries
        """
        pass

    @abstractmethod
    async def get_document_chunks(
        self,
        doc_id: str,
        page: Optional[int] = None
    ) -> List[RetrievedChunk]:
        """
        Get all chunks for a specific document.

        Args:
            doc_id: Document identifier
            page: Optional page number to filter chunks

        Returns:
            List of RetrievedChunk objects
        """
        pass

    @abstractmethod
    async def count_chunks(
        self,
        doc_id: Optional[str] = None
    ) -> int:
        """
        Count total chunks in storage.

        Args:
            doc_id: Optional document ID to count chunks for specific document

        Returns:
            Total number of chunks
        """
        pass

    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on the storage backend.

        Returns:
            Dictionary with health status information
        """
        try:
            connected = await self.is_connected()
            return {
                "status": "healthy" if connected else "unhealthy",
                "connected": connected,
                "backend": self.__class__.__name__,
            }
        except Exception as e:
            logger.exception("Health check failed: %s", e)
            return {
                "status": "unhealthy",
                "connected": False,
                "backend": self.__class__.__name__,
                "error": str(e),
            }

    async def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the storage backend.

        Returns:
            Dictionary with storage statistics
        """
        try:
            total_chunks = await self.count_chunks()
            documents = await self.list_documents(limit=1000)

            return {
                "total_documents": len(documents),
                "total_chunks": total_chunks,
                "backend": self.__class__.__name__,
            }
        except Exception as e:
            logger.exception("Failed to get stats: %s", e)
            return {
                "total_documents": 0,
                "total_chunks": 0,
                "backend": self.__class__.__name__,
                "error": str(e),
            }

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
