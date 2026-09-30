"""
Chat provider interface for generating completions and streaming text deltas.
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, List, Optional, Any


class ChatProvider(ABC):
    def __init__(self, api_key: str, model: str, **kwargs):
        self.api_key = api_key
        self.model = model
        self.config = kwargs

    @abstractmethod
    async def generate_completion(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> str:
        pass

    @abstractmethod
    async def stream_completion(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        pass

    async def generate_with_context(
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

        return await self.generate_completion(
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

        async for text_delta in self.stream_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        ):
            yield text_delta

    def has_api_key(self) -> bool:
        """Check local key presence; this does not authenticate with the provider."""
        return bool(self.api_key)

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "provider": self.__class__.__name__,
            "model": self.model,
            "api_key_present": bool(self.api_key),
        }
