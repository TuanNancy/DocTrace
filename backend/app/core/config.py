"""Application defaults and environment parsing; consumers receive resolved settings."""
import math
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Mapping, Optional, Tuple
from urllib.parse import urlparse

from dotenv import load_dotenv


def setting(default, env: str):
    return field(default=default, metadata={"env": env})


@dataclass
class AppConfig:
    """Direct construction is environment-independent; from_env reads environment only."""

    chunk_size: int = 1000
    chunk_overlap: int = 150
    min_chars_per_page: int = 50
    scanned_page_ratio_threshold: float = 0.5
    upload_max_size_mb: int = 50
    upload_max_concurrent: int = 1
    max_chunks_per_document: int = 2000
    upload_allowed_content_types: Tuple[str, ...] = field(
        default=("application/pdf",), metadata={"env": None},
    )

    milvus_host: str = "localhost"
    milvus_uri: Optional[str] = None
    milvus_token: Optional[str] = None
    milvus_port: int = 19530
    milvus_collection: str = "pdf_chunks"
    # Resolve the index default once, after the connection mode is known.
    milvus_index_type: Optional[str] = None
    milvus_metric_type: str = "COSINE"
    milvus_nlist: int = 128
    milvus_nprobe: int = 32

    model: str = setting("", "RAG_MODEL")
    temperature: float = setting(0.7, "RAG_TEMPERATURE")
    max_tokens: int = setting(2048, "RAG_MAX_TOKENS")
    embedding_model: str = ""
    embedding_batch_size: int = 64
    upstream_timeout_seconds: float = 60.0
    retrieval_top_k: int = 8
    context_max_chars: int = 12000
    min_relevance_score: float = 0.32

    openrouter_api_key: Optional[str] = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    supabase_url: Optional[str] = None
    supabase_publishable_key: Optional[str] = None
    supabase_service_role_key: Optional[str] = None
    redis_url: str = "redis://localhost:6379/0"
    rq_queue_name: str = "documents"
    document_index_timeout_seconds: int = 900
    document_delete_timeout_seconds: int = 300
    document_dispatch_poll_seconds: float = 2.0
    supabase_s3_endpoint: Optional[str] = None
    supabase_s3_region: str = "ap-southeast-2"
    supabase_s3_access_key_id: Optional[str] = None
    supabase_s3_secret_access_key: Optional[str] = None
    supabase_storage_bucket: Optional[str] = None
    cors_allow_origins: Tuple[str, ...] = (
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:3001", "http://127.0.0.1:3001",
    )

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "AppConfig":
        """Parse supported variables; no file loading or secret values in errors."""
        env = os.environ if environ is None else environ
        aliases = {
            "OPENROUTER_API_KEY": ("OPENAI_API_KEY",),
            "SUPABASE_URL": ("NEXT_PUBLIC_SUPABASE_URL",),
            "SUPABASE_PUBLISHABLE_KEY": (
                "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY",
            ),
        }
        values = {}
        for item in fields(cls):
            key = item.metadata.get("env", item.name.upper())
            if key is None:
                continue
            raw = next((env[name].strip() for name in (key, *aliases.get(key, ()))
                        if env.get(name, "").strip()), None)
            if raw is None:
                continue
            try:
                if isinstance(item.default, int):
                    value = int(raw)
                elif isinstance(item.default, float):
                    value = float(raw)
                elif isinstance(item.default, tuple):
                    value = tuple(part.strip() for part in raw.split(",") if part.strip())
                else:
                    value = raw
            except ValueError:
                raise ValueError(f"{key} has an invalid numeric value.") from None
            values[item.name] = value
        return cls(**values)

    def __post_init__(self):
        self.milvus_index_type = self.milvus_index_type or ("AUTOINDEX" if self.milvus_uri else "IVF_FLAT")
        self.openrouter_base_url = self.openrouter_base_url.rstrip("/")
        if self.embedding_model.startswith("text-embedding") and "/" not in self.embedding_model:
            self.embedding_model = f"openai/{self.embedding_model}"
        errors = self.validate()
        if errors:
            raise ValueError("Invalid configuration: " + "; ".join(errors))

    def validate(self) -> list[str]:
        errors = []
        for attr, key in (
            ("chunk_size", "CHUNK_SIZE"), ("min_chars_per_page", "MIN_CHARS_PER_PAGE"),
            ("upload_max_size_mb", "UPLOAD_MAX_SIZE_MB"), ("upload_max_concurrent", "UPLOAD_MAX_CONCURRENT"),
            ("max_chunks_per_document", "MAX_CHUNKS_PER_DOCUMENT"), ("max_tokens", "RAG_MAX_TOKENS"),
            ("embedding_batch_size", "EMBEDDING_BATCH_SIZE"), ("upstream_timeout_seconds", "UPSTREAM_TIMEOUT_SECONDS"),
            ("retrieval_top_k", "RETRIEVAL_TOP_K"), ("context_max_chars", "CONTEXT_MAX_CHARS"),
            ("milvus_nlist", "MILVUS_NLIST"), ("milvus_nprobe", "MILVUS_NPROBE"),
            ("document_index_timeout_seconds", "DOCUMENT_INDEX_TIMEOUT_SECONDS"),
            ("document_delete_timeout_seconds", "DOCUMENT_DELETE_TIMEOUT_SECONDS"),
            ("document_dispatch_poll_seconds", "DOCUMENT_DISPATCH_POLL_SECONDS"),
        ):
            value = getattr(self, attr)
            if not math.isfinite(value) or value <= 0:
                errors.append(f"{key} must be positive and finite")
        if not 0 <= self.chunk_overlap < self.chunk_size:
            errors.append("CHUNK_OVERLAP must be between 0 and CHUNK_SIZE - 1")
        if not 0 <= self.scanned_page_ratio_threshold <= 1:
            errors.append("SCANNED_PAGE_RATIO_THRESHOLD must be between 0 and 1")
        if not math.isfinite(self.min_relevance_score):
            errors.append("MIN_RELEVANCE_SCORE must be finite")
        if not math.isfinite(self.temperature) or self.temperature < 0:
            errors.append("RAG_TEMPERATURE must be non-negative and finite")
        if self.milvus_uri:
            if urlparse(self.milvus_uri).scheme not in ("http", "https") or not urlparse(self.milvus_uri).hostname:
                errors.append("MILVUS_URI must be an absolute HTTP(S) URL")
        elif self.milvus_token:
            errors.append("MILVUS_TOKEN requires MILVUS_URI")
        elif not self.milvus_host or not 1 <= self.milvus_port <= 65535:
            errors.append("MILVUS_HOST and MILVUS_PORT must identify a valid local connection")
        if not self.milvus_collection:
            errors.append("MILVUS_COLLECTION must not be empty")
        if urlparse(self.redis_url).scheme not in ("redis", "rediss") or not urlparse(self.redis_url).hostname:
            errors.append("REDIS_URL must be an absolute redis(s) URL")
        if not self.rq_queue_name:
            errors.append("RQ_QUEUE_NAME must not be empty")
        for attr in ("openrouter_base_url", "supabase_url", "supabase_s3_endpoint"):
            value = getattr(self, attr)
            if value and (urlparse(value).scheme not in ("http", "https") or not urlparse(value).hostname):
                errors.append(f"{attr.upper()} must be an absolute HTTP(S) URL")
        # A bucket/region alone is an inactive template; credentials or an endpoint opt in.
        if any((self.supabase_s3_endpoint, self.supabase_s3_access_key_id, self.supabase_s3_secret_access_key)):
            for attr in ("supabase_s3_endpoint", "supabase_s3_region", "supabase_s3_access_key_id",
                         "supabase_s3_secret_access_key", "supabase_storage_bucket"):
                if not getattr(self, attr):
                    errors.append(f"{attr.upper()} is required when S3 storage is enabled")
        return errors

    def require_openrouter(self, *, embeddings: bool = False) -> None:
        """Check service requirements when used; offline health/tests need no cloud keys."""
        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is required")
        if not (self.embedding_model if embeddings else self.model):
            raise ValueError(f"{'EMBEDDING_MODEL' if embeddings else 'RAG_MODEL'} is required")


_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Load files once. Restart the process after changing environment configuration."""
    global _config
    if _config is None:
        root = Path(__file__).resolve().parents[3]
        load_dotenv(root / ".env")
        load_dotenv(root / "backend" / ".env", override=True)
        _config = AppConfig.from_env()
    return _config
