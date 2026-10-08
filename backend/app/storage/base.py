"""
Vector store interface for indexing and retrieving document chunks.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from app.core.config import AppConfig

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    text: str
    page: int
    source: str
    score: Optional[float]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InsertResult:
    doc_id: str
    chunks_inserted: int
    warnings: List[str] = field(default_factory=list)


class VectorStore(ABC):
    def __init__(self, config: AppConfig):
        self.config = config
        self._connected = False

    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass

    @abstractmethod
    async def is_connected(self) -> bool:
        pass

    @abstractmethod
    async def ensure_collection(
        self,
        vector_dim: int,
    ) -> None:
        """Create a collection if missing; reject incompatible schemas without deleting data."""
        pass

    @abstractmethod
    async def recreate_collection(self, vector_dim: int) -> None:
        """Destructively replace the collection, deleting all existing chunks."""
        pass

    @abstractmethod
    async def insert_chunks(
        self,
        doc_id: str,
        chunks: List[Dict[str, Any]],
        vectors: List[List[float]],
        batch_size: int = 64,
        *,
        user_id: str,
    ) -> InsertResult:
        pass

    @abstractmethod
    async def search_chunks(
        self,
        query_vector: List[float],
        doc_id: Optional[str] = None,
        *,
        top_k: int,
        min_score: Optional[float],
        user_id: str,
    ) -> List[RetrievedChunk]:
        pass

    @abstractmethod
    async def get_document_chunks(self, doc_id: str, *, user_id: str) -> List[RetrievedChunk]:
        """Read an owner's document for summaries, without a similarity threshold."""
        pass

    @abstractmethod
    async def get_chunk(self, doc_id: str, chunk_id: str, *, user_id: str) -> Optional[RetrievedChunk]:
        pass

    @abstractmethod
    async def delete_document(self, doc_id: str, *, user_id: str) -> None:
        """Idempotently delete only this owner's indexed generation."""
        pass

    async def get_connection_status(self) -> Dict[str, Any]:
        """Report local connection state without probing server health."""
        try:
            connected = await self.is_connected()
            return {
                "status": "connected" if connected else "disconnected",
                "connected": connected,
                "backend": self.__class__.__name__,
            }
        except Exception as e:
            logger.exception("Could not read connection status: %s", e)
            return {
                "status": "unknown",
                "connected": False,
                "backend": self.__class__.__name__,
                "error": str(e),
            }
