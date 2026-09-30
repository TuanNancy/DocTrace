"""
Chat and embedding providers. This project uses OpenRouter only.
"""

from app.providers.base import ChatProvider
from app.providers.embeddings import OpenRouterEmbedder, get_embedder
from app.providers.factory import create_chat_provider
from app.providers.openrouter import OpenRouterChatProvider

__all__ = [
    "ChatProvider",
    "OpenRouterChatProvider",
    "OpenRouterEmbedder",
    "create_chat_provider",
    "get_embedder",
]
