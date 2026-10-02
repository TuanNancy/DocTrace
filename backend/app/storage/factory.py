"""Create the project's Milvus/Zilliz adapter from resolved application settings."""
from typing import Optional

from anyio import CancelScope

from app.core.config import AppConfig, get_config
from app.storage.base import VectorStore
from app.storage.milvus_vector_store import MilvusVectorStore


def create_vector_store(config: Optional[AppConfig] = None) -> VectorStore:
    return MilvusVectorStore(config=config if config is not None else get_config())


async def create_connected_vector_store(config: Optional[AppConfig] = None) -> VectorStore:
    store = create_vector_store(config)
    try:
        await store.connect()
    except BaseException:
        with CancelScope(shield=True):
            await store.disconnect()
        raise
    return store
