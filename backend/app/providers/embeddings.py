"""
Embeddings via OpenRouter (OpenAI-compatible `/v1/embeddings`).

Model ID is `RAGConfig.embedding_model` (e.g. `openai/text-embedding-3-small`).
"""
import logging
from functools import lru_cache
from typing import Protocol

from app.config import (
    OPENAI_EMBEDDING_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
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
        openai = __import__("openai")
        kwargs: dict = {"api_key": api_key or OPENROUTER_API_KEY}
        if OPENROUTER_BASE_URL:
            kwargs["base_url"] = OPENROUTER_BASE_URL.rstrip("/")
        self._client = openai.OpenAI(**kwargs)
        self._dim = self._get_dimension()

    def _get_dimension(self) -> int:
        """Probe API for vector size. Do not guess — wrong dim breaks Milvus insert."""
        try:
            r = self._client.embeddings.create(
                model=self._model,
                input=["dimension probe"],
            )
            return len(r.data[0].embedding)
        except Exception as e:
            logger.exception("Embedding dimension probe failed for model=%s: %s", self._model, e)
            raise RuntimeError(
                f"Embedding API failed (check OPENROUTER_API_KEY, OPENROUTER_BASE_URL, "
                f"and EMBEDDING_MODEL). Model={self._model!r}. Original error: {e}"
            ) from e

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
        api_key=OPENROUTER_API_KEY or None,
    )

