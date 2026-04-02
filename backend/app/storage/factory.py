"""
Storage factory for creating storage backend instances.
Supports multiple storage backends (Milvus, in-memory) with provider-agnostic interface.
"""
import logging
from typing import Optional, Dict, Any

from app.core.config import get_config
from app.storage.base import BaseStorage
from app.storage.milvus_storage import MilvusStorage

logger = logging.getLogger(__name__)


class StorageFactory:
    """
    Factory class for creating storage backend instances.

    This factory provides a unified interface for creating different storage
    backend instances based on configuration. It abstracts away storage-specific
    initialization details.
    """

    # Registry of available storage backends
    _backends: Dict[str, type] = {
        "milvus": MilvusStorage,
        # Add more backends as they are implemented:
        # "chroma": ChromaStorage,
    }

    @classmethod
    def register_backend(cls, name: str, backend_class: type) -> None:
        """
        Register a new storage backend class.

        Args:
            name: Backend name (e.g., "milvus", "memory", "chroma")
            backend_class: Backend class that inherits from BaseStorage
        """
        if not issubclass(backend_class, BaseStorage):
            raise ValueError(f"Backend class must inherit from BaseStorage: {backend_class}")

        cls._backends[name.lower()] = backend_class
        logger.info(f"Registered storage backend: {name}")

    @classmethod
    def create_storage(
        cls,
        storage_type: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> BaseStorage:
        """
        Create a storage backend instance based on configuration.

        Args:
            storage_type: Storage backend name (e.g., "milvus", "memory", "chroma")
                         If None, uses storage_type from global config
            config: Configuration dictionary for the storage backend
                    If None, uses config from global config
            **kwargs: Additional backend-specific configuration

        Returns:
            BaseStorage instance

        Raises:
            ValueError: If storage type is not supported or configuration is invalid
        """
        config_obj = get_config()

        # Use storage type from config if not specified
        backend_name = storage_type or config_obj.storage_type
        backend_name = backend_name.lower()

        # Check if backend is registered
        if backend_name not in cls._backends:
            available = ", ".join(cls._backends.keys())
            raise ValueError(
                f"Unsupported storage type: {backend_name}. "
                f"Available backends: {available}"
            )

        # Get backend class
        backend_class = cls._backends[backend_name]

        # Build configuration
        if config is None:
            config = cls._get_config_for_backend(backend_name, config_obj)

        # Merge with kwargs
        config.update(kwargs)

        # Create storage instance
        try:
            storage_instance = backend_class(config=config)

            logger.info(
                f"Created storage backend: {backend_name}"
            )

            return storage_instance

        except Exception as e:
            logger.exception(f"Failed to create storage backend {backend_name}: {e}")
            raise

    @classmethod
    def _get_config_for_backend(cls, backend: str, config) -> Dict[str, Any]:
        """
        Get configuration for a specific storage backend from config.

        Args:
            backend: Backend name
            config: Configuration instance

        Returns:
            Configuration dictionary for the backend
        """
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

    @classmethod
    def get_available_backends(cls) -> list[str]:
        """
        Get list of available storage backend names.

        Returns:
            List of registered backend names
        """
        return list(cls._backends.keys())

    @classmethod
    def is_backend_available(cls, backend: str) -> bool:
        """
        Check if a storage backend is available.

        Args:
            backend: Backend name to check

        Returns:
            True if backend is registered, False otherwise
        """
        return backend.lower() in cls._backends


# Convenience functions for common use cases

def create_storage(
    storage_type: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    **kwargs
) -> BaseStorage:
    """
    Create a storage backend instance using the factory.

    This is a convenience function that delegates to StorageFactory.create_storage().

    Args:
        storage_type: Storage backend name (e.g., "milvus", "memory", "chroma")
        config: Configuration dictionary for the storage backend
        **kwargs: Additional backend-specific configuration

    Returns:
        BaseStorage instance

    Example:
        >>> storage = create_storage("milvus", config={"host": "localhost", "port": 19530})
        >>> await storage.connect()
        >>> chunks = await storage.search_chunks(query_vector)
    """
    return StorageFactory.create_storage(
        storage_type=storage_type,
        config=config,
        **kwargs
    )


def get_default_storage() -> BaseStorage:
    """
    Get the default storage backend based on global configuration.

    Returns:
        BaseStorage instance configured from global config

    Example:
        >>> storage = get_default_storage()
        >>> await storage.connect()
        >>> chunks = await storage.search_chunks(query_vector)
    """
    config = get_config()
    return create_storage(
        storage_type=config.storage_type
    )


def list_backends() -> list[str]:
    """
    Get list of available storage backend names.

    Returns:
        List of registered backend names

    Example:
        >>> backends = list_backends()
        >>> print(f"Available backends: {', '.join(backends)}")
    """
    return StorageFactory.get_available_backends()


async def create_and_connect_storage(
    storage_type: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    **kwargs
) -> BaseStorage:
    """
    Create a storage backend instance and connect to it.

    This is a convenience function that creates a storage instance and
    establishes a connection in one call.

    Args:
        storage_type: Storage backend name (e.g., "milvus", "memory", "chroma")
        config: Configuration dictionary for the storage backend
        **kwargs: Additional backend-specific configuration

    Returns:
        Connected BaseStorage instance

    Example:
        >>> storage = await create_and_connect_storage("milvus")
        >>> chunks = await storage.search_chunks(query_vector)
        >>> await storage.disconnect()
    """
    storage = create_storage(
        storage_type=storage_type,
        config=config,
        **kwargs
    )
    await storage.connect()
    return storage
