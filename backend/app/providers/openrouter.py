"""
OpenRouter LLM provider implementation.
Implements BaseProvider interface for OpenRouter API access.
"""
import logging
from typing import AsyncIterator, Dict, List, Optional

from openai import AsyncOpenAI

from app.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class OpenRouterProvider(BaseProvider):
    """
    OpenRouter provider implementation using OpenAI-compatible API.

    OpenRouter provides access to multiple LLM models through a unified API.
    This provider uses the OpenAI client library with OpenRouter's base URL.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-4o-mini",
        base_url: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize OpenRouter provider.

        Args:
            api_key: OpenRouter API key
            model: Model identifier (e.g., "openai/gpt-4o-mini")
            base_url: Custom base URL (defaults to OpenRouter API)
            **kwargs: Additional configuration
        """
        super().__init__(api_key=api_key, model=model, **kwargs)

        self.base_url = base_url or "https://openrouter.ai/api/v1"
        self._client: Optional[AsyncOpenAI] = None

    def _get_client(self) -> AsyncOpenAI:
        """Get or create AsyncOpenAI client."""
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
        """
        Process text messages and return complete response.

        Args:
            messages: List of message dicts with 'role' and 'content'
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional OpenRouter-specific parameters

        Returns:
            Complete response text
        """
        client = self._get_client()

        # Build completion parameters
        params = {
            "model": self.model,
            "messages": messages,
        }

        if max_tokens is not None:
            params["max_tokens"] = max_tokens

        if temperature is not None:
            params["temperature"] = temperature

        # Add any additional kwargs
        params.update(kwargs)

        try:
            response = await client.chat.completions.create(**params)

            if not response.choices:
                logger.warning("No choices returned from OpenRouter")
                return ""

            content = response.choices[0].message.content or ""
            logger.debug(f"OpenRouter response: {len(content)} chars")

            return content

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
        """
        Stream text messages and yield tokens as they arrive.

        Args:
            messages: List of message dicts with 'role' and 'content'
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional OpenRouter-specific parameters

        Yields:
            Response tokens as they arrive
        """
        client = self._get_client()

        # Build completion parameters
        params = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }

        if max_tokens is not None:
            params["max_tokens"] = max_tokens

        if temperature is not None:
            params["temperature"] = temperature

        # Add any additional kwargs
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

    def validate_api_key(self) -> bool:
        """
        Validate OpenRouter API key.

        Returns:
            True if API key is valid, False otherwise
        """
        return super().validate_api_key()

    def get_model_info(self) -> Dict[str, any]:
        """
        Get information about the current OpenRouter model configuration.

        Returns:
            Dictionary with model information
        """
        info = super().get_model_info()
        info.update({
            "base_url": self.base_url,
            "provider": "OpenRouter",
        })
        return info

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup client."""
        if self._client:
            await self._client.close()
            self._client = None
