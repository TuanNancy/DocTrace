"""
Provider factory for creating LLM provider instances.
Supports multiple providers (OpenRouter, OpenAI, Anthropic) with provider-agnostic interface.
"""
import logging
from typing import Optional, Dict, Any

from app.core.config import get_config
from app.providers.base import BaseProvider
from app.providers.openrouter import OpenRouterProvider

logger = logging.getLogger(__name__)


class ProviderFactory:
    """
    Factory class for creating LLM provider instances.

    This factory provides a unified interface for creating different provider
    instances based on configuration. It abstracts away provider-specific
    initialization details.
    """

    # Registry of available providers
    _providers: Dict[str, type] = {
        "openrouter": OpenRouterProvider,
        # Add more providers as they are implemented:
        # "openai": OpenAIProvider,
        # "anthropic": AnthropicProvider,
    }

    @classmethod
    def register_provider(cls, name: str, provider_class: type) -> None:
        """
        Register a new provider class.

        Args:
            name: Provider name (e.g., "openrouter", "openai")
            provider_class: Provider class that inherits from BaseProvider
        """
        if not issubclass(provider_class, BaseProvider):
            raise ValueError(f"Provider class must inherit from BaseProvider: {provider_class}")

        cls._providers[name.lower()] = provider_class
        logger.info(f"Registered provider: {name}")

    @classmethod
    def create_provider(
        cls,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> BaseProvider:
        """
        Create a provider instance based on configuration.

        Args:
            provider: Provider name (e.g., "openrouter", "openai", "anthropic")
                     If None, uses provider from global config
            api_key: API key for the provider. If None, uses key from global config
            model: Model name to use. If None, uses model from global config
            **kwargs: Additional provider-specific configuration

        Returns:
            BaseProvider instance

        Raises:
            ValueError: If provider is not supported or configuration is invalid
        """
        config = get_config()

        # Use provider from config if not specified
        provider_name = provider or config.provider
        provider_name = provider_name.lower()

        # Check if provider is registered
        if provider_name not in cls._providers:
            available = ", ".join(cls._providers.keys())
            raise ValueError(
                f"Unsupported provider: {provider_name}. "
                f"Available providers: {available}"
            )

        # Get provider class
        provider_class = cls._providers[provider_name]

        # Get API key from config if not provided
        provider_api_key = api_key or cls._get_api_key_for_provider(provider_name, config)

        if not provider_api_key:
            raise ValueError(
                f"API key required for provider: {provider_name}. "
                f"Set {provider_name.upper()}_API_KEY environment variable."
            )

        # Get model from config if not provided
        provider_model = model or config.model

        # Get provider-specific config
        provider_config = config.get_provider_config()
        provider_config.update(kwargs)

        # Create provider instance
        try:
            provider_instance = provider_class(
                api_key=provider_api_key,
                model=provider_model,
                **provider_config
            )

            # Validate API key
            if not provider_instance.validate_api_key():
                raise ValueError(f"Invalid API key for provider: {provider_name}")

            logger.info(
                f"Created provider: {provider_name} with model: {provider_model}"
            )

            return provider_instance

        except Exception as e:
            logger.exception(f"Failed to create provider {provider_name}: {e}")
            raise

    @classmethod
    def _get_api_key_for_provider(cls, provider: str, config) -> Optional[str]:
        """
        Get API key for a specific provider from config.

        Args:
            provider: Provider name
            config: Configuration instance

        Returns:
            API key or None if not found
        """
        key_map = {
            "openrouter": config.openrouter_api_key,
            "openai": config.openai_api_key,
            "anthropic": config.anthropic_api_key,
        }
        return key_map.get(provider)

    @classmethod
    def get_available_providers(cls) -> list[str]:
        """
        Get list of available provider names.

        Returns:
            List of registered provider names
        """
        return list(cls._providers.keys())

    @classmethod
    def is_provider_available(cls, provider: str) -> bool:
        """
        Check if a provider is available.

        Args:
            provider: Provider name to check

        Returns:
            True if provider is registered, False otherwise
        """
        return provider.lower() in cls._providers


# Convenience functions for common use cases

def create_provider(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs
) -> BaseProvider:
    """
    Create a provider instance using the factory.

    This is a convenience function that delegates to ProviderFactory.create_provider().

    Args:
        provider: Provider name (e.g., "openrouter", "openai", "anthropic")
        api_key: API key for the provider
        model: Model name to use
        **kwargs: Additional provider-specific configuration

    Returns:
        BaseProvider instance

    Example:
        >>> provider = create_provider("openrouter", api_key="sk-...")
        >>> response = await provider.process_text_messages(messages)
    """
    return ProviderFactory.create_provider(
        provider=provider,
        api_key=api_key,
        model=model,
        **kwargs
    )


def get_default_provider() -> BaseProvider:
    """
    Get the default provider based on global configuration.

    Returns:
        BaseProvider instance configured from global config

    Example:
        >>> provider = get_default_provider()
        >>> response = await provider.process_text_messages(messages)
    """
    config = get_config()
    return create_provider(
        provider=config.provider,
        model=config.model
    )


def list_providers() -> list[str]:
    """
    Get list of available provider names.

    Returns:
        List of registered provider names

    Example:
        >>> providers = list_providers()
        >>> print(f"Available providers: {', '.join(providers)}")
    """
    return ProviderFactory.get_available_providers()
