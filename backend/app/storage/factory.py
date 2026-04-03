"""
Storage factory for creating storage backend instances.
"""
import logging
from typing import Optional, Dict, Any

from app.core.config import get_config
from app.storage.base import BaseStorage
from app.storage.milvus_storage import MilvusStorage

logger = logging.getLogger(__name__)


class StorageFactory:
    """Factory for creating storage backend instances."""

    _backends: Dict[str, type] = {
        "milvus": MilvusStorage,
    }

    @classmethod
    def create_storage(
        cls,
        storage_type: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> BaseStorage:
        config_obj = get_config()

        backend_name = (storage_type or config_obj.storage_type).lower()

        if backend_name not in cls._backends:
            available = ", ".join(cls._backends.keys())
            raise ValueError(
                f"Unsupported storage type: {backend_name}. "
                f"Available backends: {available}"
            )

        backend_class = cls._backends[backend_name]

        if config is None:
            config = cls._get_config_for_backend(backend_name, config_obj)

        config.update(kwargs)

        storage_instance = backend_class(config=config)
        logger.info("Created storage backend: %s", backend_name)
        return storage_instance

    @classmethod
    def _get_config_for_backend(cls, backend: str, config) -> Dict[str, Any]:
        backend_configs = {
            "milvus": {
                "host": config.milvus_host,
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


def create_storage(
    storage_type: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    **kwargs
) -> BaseStorage:
    """Convenience function that delegates to StorageFactory.create_storage()."""
    return StorageFactory.create_storage(
        storage_type=storage_type,
        config=config,
        **kwargs
    )


async def create_and_connect_storage(
    storage_type: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    **kwargs
) -> BaseStorage:
    """Create a storage backend instance and connect to it."""
    storage = create_storage(
        storage_type=storage_type,
        config=config,
        **kwargs
    )
    await storage.connect()
    return storage
