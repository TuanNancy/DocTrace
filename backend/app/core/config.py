"""
Core configuration. LLM and embeddings use OpenRouter only (OpenAI-compatible HTTP API).
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

from dotenv import load_dotenv

# Load .env: repo root first, then backend/.env (overrides) for local dev
_project_root = Path(__file__).resolve().parents[3]
load_dotenv(_project_root / ".env")
load_dotenv(_project_root / "backend" / ".env", override=True)


def _str(key: str, default: str = "") -> str:
    v = os.getenv(key)
    if v is None or v == "":
        return default
    return v.strip()


def _optional_str(key: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    return v.strip()


def _int(key: str, default: int) -> int:
    v = os.getenv(key)
    return int(v) if v not in (None, "") else default


def _float(key: str, default: float) -> float:
    v = os.getenv(key)
    return float(v) if v not in (None, "") else default


@dataclass
class RAGConfig:
    """Main configuration for RAG PDF Chatbot."""

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

    # ==================== OpenRouter (LLM + embeddings) ====================
    model: str = "openai/gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 4096

    # ==================== Embedding Settings ====================
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536

    # ==================== RAG Settings ====================
    retrieval_top_k: int = 8
    context_max_chars: int = 6000
    min_relevance_score: float = 0.32

    # ==================== API Keys ====================
    openrouter_api_key: Optional[str] = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    supabase_url: Optional[str] = None
    supabase_publishable_key: Optional[str] = None

    # Supabase Storage (S3-compatible API) — original PDF retention
    supabase_s3_endpoint: Optional[str] = None
    supabase_s3_region: str = "ap-southeast-2"
    supabase_s3_access_key_id: Optional[str] = None
    supabase_s3_secret_access_key: Optional[str] = None
    supabase_storage_bucket: Optional[str] = None

    # ==================== Storage ====================
    storage_type: str = "milvus"

    def __post_init__(self):
        self._load_from_env()

    def _load_from_env(self):
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

        # OpenRouter LLM
        self.model = _str("RAG_MODEL", self.model)
        self.temperature = _float("RAG_TEMPERATURE", self.temperature)
        self.max_tokens = _int("RAG_MAX_TOKENS", self.max_tokens)

        # Embedding
        self.embedding_model = _str("EMBEDDING_MODEL", self.embedding_model)
        self.embedding_dimension = _int("EMBEDDING_DIMENSION", self.embedding_dimension)

        # RAG Settings
        self.retrieval_top_k = _int("RETRIEVAL_TOP_K", self.retrieval_top_k)
        self.context_max_chars = _int("CONTEXT_MAX_CHARS", self.context_max_chars)
        self.min_relevance_score = _float("MIN_RELEVANCE_SCORE", self.min_relevance_score)

        # OpenRouter API key
        self.openrouter_api_key = _optional_str("OPENROUTER_API_KEY", self.openrouter_api_key)
        legacy_openai = _optional_str("OPENAI_API_KEY", None)
        if not self.openrouter_api_key and legacy_openai:
            self.openrouter_api_key = legacy_openai

        self.openrouter_base_url = _str("OPENROUTER_BASE_URL", self.openrouter_base_url).rstrip("/")
        self.supabase_url = _optional_str("SUPABASE_URL", self.supabase_url) or _optional_str(
            "NEXT_PUBLIC_SUPABASE_URL",
            self.supabase_url,
        )
        self.supabase_publishable_key = (
            _optional_str("SUPABASE_PUBLISHABLE_KEY", self.supabase_publishable_key)
            or _optional_str("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY", self.supabase_publishable_key)
            or _optional_str("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", self.supabase_publishable_key)
        )

        # Supabase Storage S3
        self.supabase_s3_endpoint = _optional_str("SUPABASE_S3_ENDPOINT", self.supabase_s3_endpoint)
        self.supabase_s3_region = _str("SUPABASE_S3_REGION", self.supabase_s3_region)
        self.supabase_s3_access_key_id = _optional_str("SUPABASE_S3_ACCESS_KEY_ID", self.supabase_s3_access_key_id)
        self.supabase_s3_secret_access_key = _optional_str(
            "SUPABASE_S3_SECRET_ACCESS_KEY", self.supabase_s3_secret_access_key
        )
        self.supabase_storage_bucket = _optional_str("SUPABASE_STORAGE_BUCKET", self.supabase_storage_bucket)

        # Embedding model IDs on OpenRouter use provider/model prefix
        em = (self.embedding_model or "").strip()
        if em and "/" not in em and em.startswith("text-embedding"):
            self.embedding_model = f"openai/{em}"

    def get_provider_config(self) -> dict:
        return {
            "api_key": self.openrouter_api_key,
            "base_url": self.openrouter_base_url,
            "model": self.model,
        }

    def validate(self) -> list[str]:
        errors = []
        key = self.openrouter_api_key
        if not key or key == "test-key":
            if key != "test-key":
                errors.append("OPENROUTER_API_KEY required (or set OPENAI_API_KEY to a legacy OpenRouter key)")
        return errors


# Global configuration instance
_config: Optional[RAGConfig] = None


def get_config() -> RAGConfig:
    global _config
    if _config is None:
        _config = RAGConfig()
        errors = _config.validate()
        if errors:
            import warnings
            warnings.warn(f"Configuration validation errors: {errors}")
    return _config
