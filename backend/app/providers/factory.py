"""Build an OpenRouter provider from the same settings used by its pipeline."""
from typing import Optional

from app.core.config import AppConfig, get_config
from app.providers.base import ChatProvider
from app.providers.openrouter import OpenRouterChatProvider


def create_chat_provider(config: Optional[AppConfig] = None) -> ChatProvider:
    config = config if config is not None else get_config()
    config.require_openrouter()
    return OpenRouterChatProvider(
        api_key=config.openrouter_api_key, model=config.model,
        base_url=config.openrouter_base_url, timeout=config.upstream_timeout_seconds,
    )
