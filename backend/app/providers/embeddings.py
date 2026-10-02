"""
Embeddings via OpenRouter (OpenAI-compatible `/v1/embeddings`).
"""
import logging
from functools import lru_cache
from typing import Protocol

from app.core.config import AppConfig, get_config

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    """Protocol for embedders: embed_documents and dimension."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dimension(self) -> int: ...


class OpenRouterEmbedder:
    """Generate embeddings through OpenRouter using the OpenAI-compatible SDK."""

    def __init__(self, model: str, api_key: str, base_url: str, timeout: float, batch_size: int):
        self._model = model
        openai = __import__("openai")
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )
        self._batch_size = batch_size
        try:
            self._dim = self._probe_embedding_dimension()
        except Exception:
            self._client.close()
            raise

    def _probe_embedding_dimension(self) -> int:
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
        batch_size = self._batch_size
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
def _cached_embedder(model: str, api_key: str, base_url: str, timeout: float, batch_size: int) -> Embedder:
    return OpenRouterEmbedder(
        model=model, api_key=api_key, base_url=base_url, timeout=timeout, batch_size=batch_size,
    )


def get_embedder(*, config: AppConfig | None = None) -> Embedder:
    """Cache by all client settings so injected configs never reuse another endpoint/key."""
    config = config if config is not None else get_config()
    config.require_openrouter(embeddings=True)
    return _cached_embedder(
        config.embedding_model, config.openrouter_api_key, config.openrouter_base_url,
        config.upstream_timeout_seconds, config.embedding_batch_size,
    )
