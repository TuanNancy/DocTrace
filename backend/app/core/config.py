"""
Core configuration module with provider-agnostic settings.
Supports multiple LLM providers (OpenRouter, OpenAI, Anthropic) and vector databases.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(_env_path)


def _str(key: str, default: str = "") -> str:
    """Get string environment variable."""
    return os.getenv(key, default).strip()


def _int(key: str, default: int) -> int:
    """Get integer environment variable."""
    v = os.getenv(key)
    return int(v) if v not in (None, "") else default


def _float(key: str, default: float) -> float:
    """Get float environment variable."""
    v = os.getenv(key)
    return float(v) if v not in (None, "") else default


def _bool(key: str, default: bool) -> bool:
    """Get boolean environment variable."""
    v = os.getenv(key)
    if v is None or v == "":
        return default
    return v.lower() in ("true", "1", "yes", "on")


@dataclass
class RAGConfig:
    """
    Main configuration class for RAG PDF Chatbot.
    Provider-agnostic with support for multiple LLM providers and vector databases.
    """

    # ==================== Document Processing ====================
    chunk_size: int = 1000
    chunk_overlap: int = 150
    min_chars_per_page: int = 50
    scanned_page_ratio_threshold: float = 0.5

    # ==================== Upload Settings ====================
    upload_max_size_mb: int = 50
    upload_allowed_content_types: Tuple[str, ...] = field(default_factory=lambda: ("application/pdf",))

    # ==================== Vector Database (Milvus) ====================
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "pdf_chunks"
    milvus_vector_dim: int = 1536
    milvus_index_type: str = "IVF_FLAT"
    milvus_metric_type: str = "COSINE"
    milvus_nlist: int = 128
    milvus_nprobe: int = 32

    # ==================== AI Provider Settings (Provider-Agnostic) ====================
    provider: str = "openrouter"  # openrouter, openai, anthropic
    model: str = "openai/gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 4096

    # ==================== Embedding Settings ====================
    embedding_provider: str = "openai"  # openai, sentence-transformers
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536

    # ==================== RAG Settings ====================
    retrieval_top_k: int = 8
    context_max_chars: int = 6000
    min_relevance_score: float = 0.5

    # ==================== Conversation Settings ====================
    max_conversation_turns: int = 8
    turns_to_summarize: int = 5
    turns_to_keep_full: int = 3

    # ==================== API Keys ====================
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None

    # ==================== Logging ====================
    log_level: str = "INFO"
    log_requests: bool = False

    # ==================== Storage ====================
    storage_type: str = "milvus"  # milvus, memory
    local_storage_path: str = "./rag_data"

    def __post_init__(self):
        """Load environment variables and set provider defaults."""
        self._load_from_env()
        self._set_provider_defaults()

    def _load_from_env(self):
        """Load configuration from environment variables."""
        # Document Processing
        self.chunk_size = _int("CHUNK_SIZE", self.chunk_size)
        self.chunk_overlap = _int("CHUNK_OVERLAP", self.chunk_overlap)
        self.min_chars_per_page = _int("MIN_CHARS_PER_PAGE", self.min_chars_per_page)
        self.scanned_page_ratio_threshold = _float("SCANNED_PAGE_RATIO_THRESHOLD", self.scanned_page_ratio_threshold)

        # Upload Settings
        self.upload_max_size_mb = _int("UPLOAD_MAX_SIZE_MB", self.upload_max_size_mb)

        # Vector Database
        self.milvus_host = _str("MILVUS_HOST", self.milvus_host)
        self.milvus_port = _int("MILVUS_PORT", self.milvus_port)
        self.milvus_collection = _str("MILVUS_COLLECTION", self.milvus_collection)
        self.milvus_vector_dim = _int("MILVUS_VECTOR_DIM", self.milvus_vector_dim)
        self.milvus_index_type = _str("MILVUS_INDEX_TYPE", self.milvus_index_type)
        self.milvus_metric_type = _str("MILVUS_METRIC_TYPE", self.milvus_metric_type)
        self.milvus_nlist = _int("MILVUS_NLIST", self.milvus_nlist)
        self.milvus_nprobe = _int("MILVUS_NPROBE", self.milvus_nprobe)

        # AI Provider
        self.provider = _str("RAG_PROVIDER", self.provider).lower()
        self.model = _str("RAG_MODEL", self.model)
        self.temperature = _float("RAG_TEMPERATURE", self.temperature)
        self.max_tokens = _int("RAG_MAX_TOKENS", self.max_tokens)

        # Embedding
        self.embedding_provider = _str("EMBEDDING_PROVIDER", self.embedding_provider).lower()
        self.embedding_model = _str("EMBEDDING_MODEL", self.embedding_model)
        self.embedding_dimension = _int("EMBEDDING_DIMENSION", self.embedding_dimension)

        # RAG Settings
        self.retrieval_top_k = _int("RETRIEVAL_TOP_K", self.retrieval_top_k)
        self.context_max_chars = _int("CONTEXT_MAX_CHARS", self.context_max_chars)
        self.min_relevance_score = _float("MIN_RELEVANCE_SCORE", self.min_relevance_score)

        # Conversation
        self.max_conversation_turns = _int("MAX_CONVERSATION_TURNS", self.max_conversation_turns)
        self.turns_to_summarize = _int("TURNS_TO_SUMMARIZE", self.turns_to_summarize)
        self.turns_to_keep_full = _int("TURNS_TO_KEEP_FULL", self.turns_to_keep_full)

        # API Keys
        self.openai_api_key = _str("OPENAI_API_KEY", self.openai_api_key) or None
        self.anthropic_api_key = _str("ANTHROPIC_API_KEY", self.anthropic_api_key) or None
        self.openrouter_api_key = _str("OPENROUTER_API_KEY", self.openrouter_api_key) or None

        # Logging
        self.log_level = _str("LOG_LEVEL", self.log_level).upper()
        self.log_requests = _bool("LOG_REQUESTS", self.log_requests)

        # Storage
        self.storage_type = _str("STORAGE_TYPE", self.storage_type).lower()
        self.local_storage_path = _str("LOCAL_STORAGE_PATH", self.local_storage_path)

    def _set_provider_defaults(self):
        """Set provider-specific defaults based on selected provider."""
        provider_defaults = {
            "openrouter": {
                "model": "openai/gpt-4o-mini",
                "base_url": "https://openrouter.ai/api/v1",
            },
            "openai": {
                "model": "gpt-4o-mini",
                "base_url": None,
            },
            "anthropic": {
                "model": "claude-3-haiku-20240307",
                "base_url": None,
            },
        }

        if self.provider in provider_defaults:
            defaults = provider_defaults[self.provider]
            # Only set defaults if not explicitly provided
            if self.model == "openai/gpt-4o-mini" and self.provider != "openrouter":
                self.model = defaults["model"]

    def get_provider_config(self) -> dict:
        """Get provider-specific configuration."""
        provider_configs = {
            "openrouter": {
                "api_key": self.openrouter_api_key,
                "base_url": "https://openrouter.ai/api/v1",
                "model": self.model,
            },
            "openai": {
                "api_key": self.openai_api_key,
                "base_url": None,
                "model": self.model,
            },
            "anthropic": {
                "api_key": self.anthropic_api_key,
                "base_url": None,
                "model": self.model,
            },
        }
        return provider_configs.get(self.provider, {})

    def get_embedding_config(self) -> dict:
        """Get embedding provider configuration."""
        embedding_configs = {
            "openai": {
                "api_key": self.openai_api_key,
                "model": self.embedding_model,
                "dimension": self.embedding_dimension,
            },
            "sentence-transformers": {
                "model": self.embedding_model,
                "dimension": self.embedding_dimension,
            },
        }
        return embedding_configs.get(self.embedding_provider, {})

    def validate(self) -> list[str]:
        """
        Validate configuration and return list of errors.
        Returns empty list if configuration is valid.
        """
        errors = []

        # Validate provider
        if self.provider not in ["openrouter", "openai", "anthropic"]:
            errors.append(f"Invalid provider: {self.provider}")

        # Validate API key for selected provider
        provider_key_map = {
            "openrouter": self.openrouter_api_key,
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
        }
        required_key = provider_key_map.get(self.provider)
        if not required_key or required_key == "test-key":
            # Allow test-key for testing
            if required_key != "test-key":
                errors.append(f"API key required for provider: {self.provider}")

        # Validate embedding provider
        if self.embedding_provider not in ["openai", "sentence-transformers"]:
            errors.append(f"Invalid embedding provider: {self.embedding_provider}")

        # Validate storage type
        if self.storage_type not in ["milvus", "memory"]:
            errors.append(f"Invalid storage type: {self.storage_type}")

        # Validate Milvus settings if using Milvus
        if self.storage_type == "milvus":
            if not self.milvus_host:
                errors.append("Milvus host required when storage_type=milvus")
            if not self.milvus_port:
                errors.append("Milvus port required when storage_type=milvus")

        return errors


# Global configuration instance
_config: Optional[RAGConfig] = None


def get_config() -> RAGConfig:
    """Get or create global configuration instance."""
    global _config
    if _config is None:
        _config = RAGConfig()
        errors = _config.validate()
        if errors:
            import warnings
            warnings.warn(f"Configuration validation errors: {errors}")
    return _config


def reset_config():
    """Reset global configuration (useful for testing)."""
    global _config
    _config = None
