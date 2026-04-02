"""
LLM and embedding providers. This project uses **OpenRouter only**:
- `openrouter.py` — chat / streaming
- `embeddings.py` — embeddings (OpenAI-compatible API to OpenRouter)
- `factory.py` — `create_provider()` → `OpenRouterProvider`
"""

from app.providers.base import BaseProvider
from app.providers.embeddings import get_embedder
from app.providers.factory import create_provider, get_default_provider
from app.providers.openrouter import OpenRouterProvider

__all__ = [
    "BaseProvider",
    "OpenRouterProvider",
    "create_provider",
    "get_default_provider",
    "get_embedder",
]
