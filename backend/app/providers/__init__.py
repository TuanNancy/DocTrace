"""
LLM provider. This project uses OpenRouter only.
"""

from app.providers.base import BaseProvider
from app.providers.embeddings import get_embedder
from app.providers.factory import create_provider
from app.providers.openrouter import OpenRouterProvider

__all__ = [
    "BaseProvider",
    "create_provider",
    "get_embedder",
]
