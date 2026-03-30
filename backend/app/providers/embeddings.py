"""
Embedding provider: OpenAI embeddings (text-embedding-3-small, etc.).
"""
import logging
from functools import lru_cache
from typing import Protocol

from app.config import (
    OPENAI_API_KEY,
    OPENAI_EMBEDDING_MODEL,
)

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    """Protocol for embedders: embed_documents and dimension."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dimension(self) -> int: ...


class OpenAIEmbedder:
    """OpenAI embeddings (e.g. text-embedding-3-small)."""

    def __init__(self, model: str = OPENAI_EMBEDDING_MODEL, api_key: str | None = None):
        self._model = model
        self._client = __import__("openai").OpenAI(api_key=api_key or OPENAI_API_KEY)
        self._dim = self._get_dimension()

    def _get_dimension(self) -> int:
        # text-embedding-3-small = 1536, ada-002 = 1536
        try:
            r = self._client.embeddings.create(
                model=self._model,
                input=["dimension probe"],
            )
            return len(r.data[0].embedding)
        except Exception as e:
            logger.warning("Could not infer OpenAI embedding dim, defaulting to 1536: %s", e)
            return 1536

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # OpenAI allows batch; cap at 2048 inputs per request to be safe
        batch_size = 2048
        out: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            r = self._client.embeddings.create(model=self._model, input=chunk)
            for d in sorted(r.data, key=lambda x: x.index):
                out.append(d.embedding)
        return out

    @property
    def dimension(self) -> int:
        return self._dim


@lru_cache(maxsize=2)
def get_embedder(
    openai_model: str | None = None,
) -> Embedder:
    """
    Return cached OpenAI embedder instance.
    """
    return OpenAIEmbedder(
        model=openai_model or OPENAI_EMBEDDING_MODEL,
        api_key=OPENAI_API_KEY or None,
    )

