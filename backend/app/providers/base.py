"""
Base provider interface for LLM operations.
Defines the contract that all LLM providers must implement.
"""
import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class BaseProvider(ABC):
    """
    Abstract base class for LLM providers.

    All providers must implement these methods to ensure consistent
    interaction with different LLM APIs (OpenRouter, OpenAI, Anthropic, etc.).
    """

    def __init__(self, api_key: str, model: str, **kwargs):
        """
        Initialize the provider.

        Args:
            api_key: API key for the provider
            model: Model name to use
            **kwargs: Additional provider-specific configuration
        """
        self.api_key = api_key
        self.model = model
        self.config = kwargs

    @abstractmethod
    async def process_text_messages(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> str:
        """
        Process text-only messages and return complete response.

        Args:
            messages: List of message dicts with 'role' and 'content'
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional provider-specific parameters

        Returns:
            Complete response text
        """
        pass

    @abstractmethod
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
            **kwargs: Additional provider-specific parameters

        Yields:
            Response tokens as they arrive
        """
        pass

    async def process_with_context(
        self,
        query: str,
        context: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> str:
        """
        Convenience method for RAG: process query with document context.

        Args:
            query: User query
            context: Document context to include
            system_prompt: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional provider-specific parameters

        Returns:
            Complete response text
        """
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Combine context and query
        if context:
            user_content = f"Context:\n{context}\n\nQuestion: {query}"
        else:
            user_content = query

        messages.append({"role": "user", "content": user_content})

        return await self.process_text_messages(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )

    async def stream_with_context(
        self,
        query: str,
        context: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        """
        Convenience method for RAG: stream query with document context.

        Args:
            query: User query
            context: Document context to include
            system_prompt: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional provider-specific parameters

        Yields:
            Response tokens as they arrive
        """
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Combine context and query
        if context:
            user_content = f"Context:\n{context}\n\nQuestion: {query}"
        else:
            user_content = query

        messages.append({"role": "user", "content": user_content})

        async for token in self.stream_text_messages(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        ):
            yield token

    def validate_api_key(self) -> bool:
        """
        Validate that the API key is present and non-empty.

        Returns:
            True if API key is valid, False otherwise
        """
        if not self.api_key:
            logger.warning("API key is missing or empty")
            return False

        # Allow test-key for testing purposes
        if self.api_key == "test-key":
            logger.info("Using test API key")
            return True

        return True

    def get_model_info(self) -> Dict[str, Any]:
        """
        Get information about the current model configuration.

        Returns:
            Dictionary with model information
        """
        return {
            "provider": self.__class__.__name__,
            "model": self.model,
            "api_key_present": bool(self.api_key),
        }

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        pass
