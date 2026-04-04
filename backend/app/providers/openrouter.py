"""
OpenRouter LLM provider implementation.
"""
import logging
from typing import AsyncIterator, Dict, List, Optional

from openai import AsyncOpenAI

from app.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class OpenRouterProvider(BaseProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-4o-mini",
        base_url: Optional[str] = None,
        **kwargs
    ):
        super().__init__(api_key=api_key, model=model, **kwargs)
        self.base_url = base_url or "https://openrouter.ai/api/v1"
        self._client: Optional[AsyncOpenAI] = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url.rstrip("/") or "https://openrouter.ai/api/v1",
            )
        return self._client

    async def process_text_messages(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> str:
        client = self._get_client()
        params = {"model": self.model, "messages": messages}
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        if temperature is not None:
            params["temperature"] = temperature
        params.update(kwargs)

        try:
            response = await client.chat.completions.create(**params)
            if not response.choices:
                logger.warning("No choices returned from OpenRouter")
                return ""
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.exception("OpenRouter API error: %s", e)
            raise RuntimeError(f"OpenRouter API error: {e}") from e

    async def stream_text_messages(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        client = self._get_client()
        params = {"model": self.model, "messages": messages, "stream": True}
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        if temperature is not None:
            params["temperature"] = temperature
        params.update(kwargs)

        try:
            stream = await client.chat.completions.create(**params)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except Exception as e:
            logger.exception("OpenRouter streaming error: %s", e)
            raise RuntimeError(f"OpenRouter streaming error: {e}") from e
