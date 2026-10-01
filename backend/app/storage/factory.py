"""
Factory for creating vector stores used to index and retrieve chunks.
"""
import logging
from typing import Optional, Dict, Any
from anyio import CancelScope

from app.core.config import get_config
from app.storage.base import VectorStore
from app.storage.milvus_vector_store import MilvusVectorStore

logger = logging.getLogger(__name__)


class VectorStoreFactory:
    """Factory for creating vector store instances."""

    _backends: Dict[str, type] = {
        "milvus": MilvusVectorStore,
    }

    @classmethod
    def create_vector_store(
        cls,
        vector_store_type: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> VectorStore:
        config_obj = get_config()

        backend_name = (vector_store_type or config_obj.vector_store_type).lower()

        if backend_name not in cls._backends:
            available = ", ".join(cls._backends.keys())
            raise ValueError(
                f"Unsupported vector store type: {backend_name}. "
                f"Available backends: {available}"
            )

        backend_class = cls._backends[backend_name]

        if config is None:
            config = cls._get_config_for_backend(backend_name, config_obj)

        config.update(kwargs)

        vector_store = backend_class(config=config)
        logger.info("Created vector store: %s", backend_name)
        return vector_store

    @classmethod
    def _get_config_for_backend(cls, backend: str, config) -> Dict[str, Any]:
        backend_configs = {
            "milvus": {
                "host": config.milvus_host,
                "uri": config.milvus_uri,
                "token": config.milvus_token,
                "port": config.milvus_port,
                "collection": config.milvus_collection,
                "vector_dim": config.milvus_vector_dim,
                "index_type": config.milvus_index_type,
                "metric_type": config.milvus_metric_type,
                "nlist": config.milvus_nlist,
                "nprobe": config.milvus_nprobe,
            },
        }
        return backend_configs.get(backend, {})


def create_vector_store(
    vector_store_type: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    **kwargs
) -> VectorStore:
    """Create a vector store without opening a connection."""
    return VectorStoreFactory.create_vector_store(
        vector_store_type=vector_store_type,
        config=config,
        **kwargs
    )


async def create_connected_vector_store(
    vector_store_type: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    **kwargs
) -> VectorStore:
    """Create a vector store and open its connection; the caller must disconnect it."""
    vector_store = create_vector_store(
        vector_store_type=vector_store_type,
        config=config,
        **kwargs
    )
    try:
        await vector_store.connect()
    except BaseException:
        with CancelScope(shield=True):
            await vector_store.disconnect()
        raise
    return vector_store
