"""
Settings from .env for backend (Milvus, embedding, upload limits).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from backend root
_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_env_path)


def _str(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _int(key: str, default: int) -> int:
    v = os.getenv(key)
    return int(v) if v not in (None, "") else default


# Milvus
MILVUS_HOST = _str("MILVUS_HOST", "localhost")
MILVUS_PORT = _int("MILVUS_PORT", 19530)
MILVUS_COLLECTION = _str("MILVUS_COLLECTION", "pdf_chunks")
MILVUS_VECTOR_DIM = _int("MILVUS_VECTOR_DIM", 1536)  # OpenAI; bge-m3 is 1024

# Embedding provider: "openai" | "huggingface"
EMBEDDING_PROVIDER = _str("EMBEDDING_PROVIDER", "openai")
OPENAI_API_KEY = _str("OPENAI_API_KEY")
OPENAI_EMBEDDING_MODEL = _str("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
HUGGINGFACE_EMBEDDING_MODEL = _str(
    "HUGGINGFACE_EMBEDDING_MODEL", "BAAI/bge-m3"
)

# Upload
UPLOAD_MAX_SIZE_MB = _int("UPLOAD_MAX_SIZE_MB", 50)
UPLOAD_ALLOWED_CONTENT_TYPES = ("application/pdf",)

# Chunking
CHUNK_SIZE = _int("CHUNK_SIZE", 1000)
CHUNK_OVERLAP = _int("CHUNK_OVERLAP", 150)

# Scanned PDF: min chars per page to consider "has text"
MIN_CHARS_PER_PAGE = _int("MIN_CHARS_PER_PAGE", 50)
