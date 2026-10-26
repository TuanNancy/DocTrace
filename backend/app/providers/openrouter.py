"""
OpenRouter LLM provider implementation.
"""
import asyncio
import logging
from time import perf_counter
from typing import AsyncIterator, Dict, List, Optional

import httpx
from openai import AsyncOpenAI

from app.core.config import AppConfig
from app.providers.base import ChatProvider
from app.providers.usage import ProviderCall, update_from_chunk, update_from_response

logger = logging.getLogger(__name__)


class OpenRouterChatProvider(ChatProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout: float,
    ):
        super().__init__(api_key=api_key, model=model)
        self.base_url = base_url
        self.timeout = timeout
        self._client: Optional[AsyncOpenAI] = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                # One logical ProviderCall must map to one HTTP attempt; SDK
                # retries would add untracked provider calls and cost.
                max_retries=0,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def generate_completion(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        *,
        usage: Optional[ProviderCall] = None,
        **kwargs
    ) -> str:
        client = self._get_client()
        params = {"model": self.model, "messages": messages}
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        if temperature is not None:
            params["temperature"] = temperature
        params.update(kwargs)

        started = perf_counter()
        try:
            response = await client.chat.completions.create(**params)
            update_from_response(usage, response, round((perf_counter() - started) * 1000))
            if not response.choices:
                logger.warning("No choices returned from OpenRouter")
                return ""
            return response.choices[0].message.content or ""
        except asyncio.CancelledError:
            if usage is not None:
                usage.mark_error("cancelled")
            raise
        except Exception as e:
            if usage is not None:
                usage.mark_error()
            logger.exception("OpenRouter API error: %s", e)
            raise RuntimeError(f"OpenRouter API error: {e}") from e
        finally:
            if usage is not None:
                usage.latency_ms = round((perf_counter() - started) * 1000)

    async def stream_completion(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        *,
        usage: Optional[ProviderCall] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        client = self._get_client()
        params = {
            "model": self.model, "messages": messages, "stream": True,
            # OpenRouter returns usage automatically today; keep the explicit
            # option for OpenAI-compatible endpoints and older deployments.
            "stream_options": {"include_usage": True},
        }
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        if temperature is not None:
            params["temperature"] = temperature
        params.update(kwargs)

        started = perf_counter()
        stream = None
        try:
            stream = await client.chat.completions.create(**params)
            async for chunk in stream:
                # The final OpenRouter usage chunk has usage, an id, and empty
                # choices; capture it before checking choices.
                update_from_chunk(usage, chunk)
                if getattr(chunk, "error", None):
                    raise RuntimeError("OpenRouter returned a streaming error.")
                if not chunk.choices:
                    continue
                if getattr(chunk.choices[0], "finish_reason", None) == "error":
                    raise RuntimeError("OpenRouter could not complete the response.")
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except asyncio.CancelledError:
            if usage is not None:
                usage.mark_error("cancelled")
            raise
        except GeneratorExit:
            if usage is not None:
                usage.mark_error("cancelled")
            raise
        except Exception as e:
            if usage is not None:
                usage.mark_error()
            logger.exception("OpenRouter streaming error: %s", e)
            raise RuntimeError(f"OpenRouter streaming error: {e}") from e
        finally:
            if usage is not None:
                usage.latency_ms = round((perf_counter() - started) * 1000)
            if stream is not None:
                close = getattr(stream, "close", None) or getattr(stream, "aclose", None)
                if close:
                    await close()


async def fetch_generation(config: AppConfig, generation_id: str) -> dict | None:
    """Best-effort exact cost lookup for a completed OpenRouter generation."""
    try:
        async with httpx.AsyncClient(timeout=min(config.upstream_timeout_seconds, 10.0)) as client:
            response = await client.get(
                f"{config.openrouter_base_url.rstrip('/')}/generation",
                params={"id": generation_id},
                headers={"Authorization": f"Bearer {config.openrouter_api_key}"},
            )
        if response.status_code != 200:
            logger.warning(
                "OpenRouter generation lookup failed status=%s generation=%s",
                response.status_code, generation_id,
            )
            return None
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, dict) else None
    except Exception:
        logger.warning("OpenRouter generation lookup errored generation=%s", generation_id, exc_info=True)
        return None
