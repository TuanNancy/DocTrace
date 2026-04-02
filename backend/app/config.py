"""
Backward compatibility wrapper for configuration.

This module maintains the old configuration API while using the new
core configuration system. All old configuration variables are available
for backward compatibility with existing code.

New code should use app.core.config.get_config() instead.
"""

# Import the new configuration system
from app.core.config import get_config, RAGConfig

# Get the global configuration instance
_config = get_config()

# ==================== Milvus Configuration ====================
# Backward compatibility exports
MILVUS_HOST = _config.milvus_host
MILVUS_PORT = _config.milvus_port
MILVUS_COLLECTION = _config.milvus_collection
MILVUS_VECTOR_DIM = _config.milvus_vector_dim

# ==================== OpenAI-compatible SDK (routed to OpenRouter) ====================
# OPENAI_* names are legacy aliases — keys and base URL are OpenRouter.
OPENAI_API_KEY = _config.openrouter_api_key
OPENAI_EMBEDDING_MODEL = _config.embedding_model
OPENAI_BASE_URL = _config.openrouter_base_url

# ==================== Upload Configuration ====================
# Backward compatibility exports
UPLOAD_MAX_SIZE_MB = _config.upload_max_size_mb
UPLOAD_ALLOWED_CONTENT_TYPES = _config.upload_allowed_content_types

# ==================== Chunking Configuration ====================
# Backward compatibility exports
CHUNK_SIZE = _config.chunk_size
CHUNK_OVERLAP = _config.chunk_overlap

# ==================== PDF Processing Configuration ====================
# Backward compatibility exports
MIN_CHARS_PER_PAGE = _config.min_chars_per_page

# ==================== OpenRouter Configuration ====================
OPENROUTER_API_KEY = _config.openrouter_api_key
OPENROUTER_BASE_URL = _config.openrouter_base_url
OPENROUTER_CHAT_MODEL = _config.model


# ==================== Utility Functions ====================

def get_config_instance() -> RAGConfig:
    """
    Get the global configuration instance.

    Returns:
        RAGConfig: The global configuration instance

    Example:
        >>> config = get_config_instance()
        >>> print(config.milvus_host)
    """
    return _config


def reload_config() -> RAGConfig:
    """
    Reload the configuration from environment variables.

    This is useful for testing or when environment variables change.

    Returns:
        RAGConfig: The new configuration instance

    Example:
        >>> config = reload_config()
        >>> print(config.milvus_host)
    """
    global _config
    from app.core.config import reset_config
    reset_config()
    _config = get_config()

    # Update module-level variables for backward compatibility
    global MILVUS_HOST, MILVUS_PORT, MILVUS_COLLECTION, MILVUS_VECTOR_DIM
    global OPENAI_API_KEY, OPENAI_EMBEDDING_MODEL, OPENAI_BASE_URL
    global UPLOAD_MAX_SIZE_MB, UPLOAD_ALLOWED_CONTENT_TYPES
    global CHUNK_SIZE, CHUNK_OVERLAP
    global MIN_CHARS_PER_PAGE
    global OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_CHAT_MODEL

    MILVUS_HOST = _config.milvus_host
    MILVUS_PORT = _config.milvus_port
    MILVUS_COLLECTION = _config.milvus_collection
    MILVUS_VECTOR_DIM = _config.milvus_vector_dim
    OPENAI_API_KEY = _config.openrouter_api_key
    OPENAI_EMBEDDING_MODEL = _config.embedding_model
    OPENAI_BASE_URL = _config.openrouter_base_url
    UPLOAD_MAX_SIZE_MB = _config.upload_max_size_mb
    UPLOAD_ALLOWED_CONTENT_TYPES = _config.upload_allowed_content_types
    CHUNK_SIZE = _config.chunk_size
    CHUNK_OVERLAP = _config.chunk_overlap
    MIN_CHARS_PER_PAGE = _config.min_chars_per_page
    OPENROUTER_API_KEY = _config.openrouter_api_key
    OPENROUTER_BASE_URL = _config.openrouter_base_url
    OPENROUTER_CHAT_MODEL = _config.model

    return _config


def get_milvus_config() -> dict:
    """
    Get Milvus configuration as a dictionary.

    Returns:
        dict: Milvus configuration

    Example:
        >>> milvus_config = get_milvus_config()
        >>> print(milvus_config['host'])
    """
    return {
        "host": _config.milvus_host,
        "port": _config.milvus_port,
        "collection": _config.milvus_collection,
        "vector_dim": _config.milvus_vector_dim,
        "index_type": _config.milvus_index_type,
        "metric_type": _config.milvus_metric_type,
        "nlist": _config.milvus_nlist,
        "nprobe": _config.milvus_nprobe,
    }


def get_openai_config() -> dict:
    """
    Get OpenAI configuration as a dictionary.

    Returns:
        dict: OpenAI configuration

    Example:
        >>> openai_config = get_openai_config()
        >>> print(openai_config['api_key'])
    """
    return {
        "api_key": _config.openrouter_api_key,
        "base_url": _config.openrouter_base_url,
        "embedding_model": _config.embedding_model,
        "embedding_dimension": _config.embedding_dimension,
    }


def get_openrouter_config() -> dict:
    """
    Get OpenRouter configuration as a dictionary.

    Returns:
        dict: OpenRouter configuration

    Example:
        >>> openrouter_config = get_openrouter_config()
        >>> print(openrouter_config['api_key'])
    """
    return {
        "api_key": _config.openrouter_api_key,
        "base_url": _config.openrouter_base_url,
        "model": _config.model,
    }


def get_chunking_config() -> dict:
    """
    Get chunking configuration as a dictionary.

    Returns:
        dict: Chunking configuration

    Example:
        >>> chunking_config = get_chunking_config()
        >>> print(chunking_config['chunk_size'])
    """
    return {
        "chunk_size": _config.chunk_size,
        "chunk_overlap": _config.chunk_overlap,
        "min_chars_per_page": _config.min_chars_per_page,
    }


def get_upload_config() -> dict:
    """
    Get upload configuration as a dictionary.

    Returns:
        dict: Upload configuration

    Example:
        >>> upload_config = get_upload_config()
        >>> print(upload_config['max_size_mb'])
    """
    return {
        "max_size_mb": _config.upload_max_size_mb,
        "allowed_content_types": _config.upload_allowed_content_types,
    }


# ==================== Deprecated Functions ====================
# These functions are maintained for backward compatibility but should not be used in new code

def _str(key: str, default: str = "") -> str:
    """
    DEPRECATED: Use app.core.config.get_config() instead.

    Get string environment variable.
    """
    import os
    return os.getenv(key, default).strip()


def _int(key: str, default: int) -> int:
    """
    DEPRECATED: Use app.core.config.get_config() instead.

    Get integer environment variable.
    """
    import os
    v = os.getenv(key)
    return int(v) if v not in (None, "") else default


# ==================== Module Exports ====================
__all__ = [
    # Configuration instance
    "get_config_instance",
    "reload_config",
    # Milvus
    "MILVUS_HOST",
    "MILVUS_PORT",
    "MILVUS_COLLECTION",
    "MILVUS_VECTOR_DIM",
    "get_milvus_config",
    # OpenAI
    "OPENAI_API_KEY",
    "OPENAI_EMBEDDING_MODEL",
    "OPENAI_BASE_URL",
    "get_openai_config",
    # OpenRouter
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_CHAT_MODEL",
    "get_openrouter_config",
    # Upload
    "UPLOAD_MAX_SIZE_MB",
    "UPLOAD_ALLOWED_CONTENT_TYPES",
    "get_upload_config",
    # Chunking
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "MIN_CHARS_PER_PAGE",
    "get_chunking_config",
    # Deprecated
    "_str",
    "_int",
]
