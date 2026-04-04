"""
Base storage interface for vector database operations.
Defines the contract that all storage backends must implement.
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


class BaseStorage(ABC):
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
        recreate: bool = False
    ) -> None:
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

    async def health_check(self) -> Dict[str, Any]:
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
