"""
LLM provider factory. This project uses OpenRouter only.
"""
import logging
from typing import Optional, Dict

from app.core.config import get_config
from app.providers.base import BaseProvider
from app.providers.openrouter import OpenRouterProvider

logger = logging.getLogger(__name__)


class ProviderFactory:
    """Factory for creating LLM provider instances."""

    _providers: Dict[str, type] = {
        "openrouter": OpenRouterProvider,
    }

    @classmethod
    def create_provider(
        cls,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> BaseProvider:
        config = get_config()

        provider_name = (provider or config.provider).lower()

        if provider_name not in cls._providers:
            available = ", ".join(cls._providers.keys())
            raise ValueError(
                f"Unsupported provider: {provider_name}. "
                f"Available providers: {available}"
            )

        provider_class = cls._providers[provider_name]
        provider_api_key = api_key or config.openrouter_api_key

        if not provider_api_key:
            raise ValueError(f"API key required for provider: {provider_name}")

        provider_model = model or config.model
        provider_config = config.get_provider_config()
        provider_config.update(kwargs)
        provider_config.pop("api_key", None)
        provider_config.pop("model", None)

        provider_instance = provider_class(
            api_key=provider_api_key,
            model=provider_model,
            **provider_config
        )

        if not provider_instance.validate_api_key():
            raise ValueError(f"Invalid API key for provider: {provider_name}")

        logger.info("Created provider: %s with model: %s", provider_name, provider_model)
        return provider_instance


def create_provider(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs
) -> BaseProvider:
    """Convenience function that delegates to ProviderFactory.create_provider()."""
    return ProviderFactory.create_provider(
        provider=provider,
        api_key=api_key,
        model=model,
        **kwargs
    )
