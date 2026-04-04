"""
Base provider interface for LLM operations.
"""
import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class BaseProvider(ABC):
    def __init__(self, api_key: str, model: str, **kwargs):
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
        pass

    @abstractmethod
    async def stream_text_messages(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> AsyncIterator[str]:
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
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        user_content = f"Context:\n{context}\n\nQuestion: {query}" if context else query
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
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        user_content = f"Context:\n{context}\n\nQuestion: {query}" if context else query
        messages.append({"role": "user", "content": user_content})

        async for token in self.stream_text_messages(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        ):
            yield token

    def validate_api_key(self) -> bool:
        if not self.api_key:
            logger.warning("API key is missing or empty")
            return False
        if self.api_key == "test-key":
            logger.info("Using test API key")
            return True
        return True

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "provider": self.__class__.__name__,
            "model": self.model,
            "api_key_present": bool(self.api_key),
        }
