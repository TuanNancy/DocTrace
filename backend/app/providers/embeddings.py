"""
Embeddings via OpenRouter (OpenAI-compatible `/v1/embeddings`).
"""
import logging
from functools import lru_cache
from typing import Protocol

from app.core.config import get_config

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    """Protocol for embedders: embed_documents and dimension."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dimension(self) -> int: ...


class OpenAIEmbedder:
    """OpenAI embeddings via OpenRouter."""

    def __init__(self, model: str, api_key: str):
        self._model = model
        openai = __import__("openai")
        config = get_config()
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=config.openrouter_base_url.rstrip("/"),
        )
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
                f"Embedding API failed (check OPENROUTER_API_KEY and EMBEDDING_MODEL). "
                f"Model={self._model!r}. Original error: {e}"
            ) from e

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
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
def get_embedder(model: str | None = None) -> Embedder:
    """Return cached OpenAI embedder instance."""
    config = get_config()
    return OpenAIEmbedder(
        model=model or config.embedding_model,
        api_key=config.openrouter_api_key,
    )
