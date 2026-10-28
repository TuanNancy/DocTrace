"""
Embeddings via OpenRouter (OpenAI-compatible `/v1/embeddings`).
"""
import logging
from functools import lru_cache
from time import perf_counter
from typing import Protocol

from app.core.config import AppConfig, get_config
from app.providers.usage import ProviderCall

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    """Protocol for embedders: embed_documents and dimension."""

    def embed_documents(
        self, texts: list[str], *, usage: ProviderCall | None = None,
    ) -> list[list[float]]: ...

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
            # Embedding batches are metered; SDK retries would create
            # untracked calls. RQ owns document-level retries.
            max_retries=0,
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
            logger.exception("embedding_probe_failed", extra={"model": self._model})
            raise RuntimeError(
                "Embedding API failed (check OPENROUTER_API_KEY and EMBEDDING_MODEL)."
            ) from e

    def embed_documents(
        self, texts: list[str], *, usage: ProviderCall | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []
        batch_size = self._batch_size
        out: list[list[float]] = []
        started = perf_counter()
        try:
            for i in range(0, len(texts), batch_size):
                chunk = texts[i : i + batch_size]
                r = self._client.embeddings.create(model=self._model, input=chunk)
                if usage is not None:
                    # Embedding batches share one logical call row; batch
                    # responses are not chat generations, so never reconcile
                    # them through GET /generation.
                    response_usage = getattr(r, "usage", None)
                    if response_usage is None:
                        usage.mark_missing_usage()
                    else:
                        usage.apply_usage(response_usage)
                for d in sorted(r.data, key=lambda x: x.index):
                    out.append(d.embedding)
            return out
        except Exception:
            if usage is not None:
                usage.mark_error()
            raise
        finally:
            if usage is not None:
                usage.latency_ms = round((perf_counter() - started) * 1000)

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
