"""
Vector store interface for indexing and retrieving document chunks.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
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
    doc_id: str
    chunks_inserted: int
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class VectorStore(ABC):
    def __init__(self, config: Dict[str, Any]):
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
        batch_size: int = 64
    ) -> InsertResult:
        pass

    @abstractmethod
    async def search_chunks(
        self,
        query_vector: List[float],
        doc_id: Optional[str] = None,
        top_k: int = 8,
        min_score: Optional[float] = None
    ) -> List[RetrievedChunk]:
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
