"""
OpenRouter streaming client: AsyncOpenAI with base_url=openrouter.ai/api/v1.
Async generator stream_answer() yields tokens from chat completions.
"""
import logging
from typing import AsyncIterator

from openai import AsyncOpenAI

from app.config import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_CHAT_MODEL,
)

logger = logging.getLogger(__name__)


def _get_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL.rstrip("/") or "https://openrouter.ai/api/v1",
    )


async def stream_answer(
    messages: list[dict[str, str]],
    model: str | None = None,
) -> AsyncIterator[str]:
    """
    Stream chat completion tokens from OpenRouter.
    messages: list of {"role": "system"|"user"|"assistant", "content": "..."}
    Yields each token (delta content) as it arrives.
    """
    client = _get_client()
    model = model or OPENROUTER_CHAT_MODEL
    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
    )
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content
