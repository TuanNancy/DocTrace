"""
LLM provider factory. This project uses OpenRouter only.
"""
import logging
from typing import Optional

from app.core.config import get_config
from app.providers.base import ChatProvider
from app.providers.openrouter import OpenRouterChatProvider

logger = logging.getLogger(__name__)


def create_chat_provider(
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs
) -> ChatProvider:
    config = get_config()

    provider_api_key = api_key or config.openrouter_api_key
    if not provider_api_key:
        raise ValueError("API key required for OpenRouter provider")

    provider_model = model or config.model
    provider_config = config.get_chat_provider_config()
    provider_config.update(kwargs)
    provider_config.pop("api_key", None)
    provider_config.pop("model", None)

    provider_instance = OpenRouterChatProvider(
        api_key=provider_api_key,
        model=provider_model,
        **provider_config
    )

    if not provider_instance.has_api_key():
        raise ValueError("API key required for OpenRouter chat provider")

    logger.info("Created OpenRouter chat provider with model: %s", provider_model)
    return provider_instance
