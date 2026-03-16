"""
Milvus vector store provider:
- Collection schema definition
- Collection creation / index management
- Batch insert utilities
"""
import logging
import uuid
from typing import Any

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    drop_collection,
    has_collection,
    utility,
)

from app.config import MILVUS_COLLECTION, MILVUS_HOST, MILVUS_PORT, MILVUS_VECTOR_DIM

logger = logging.getLogger(__name__)

# Collection field names
COLLECTION_NAME = MILVUS_COLLECTION
PK_FIELD = "id"
DOC_ID_FIELD = "doc_id"
TEXT_FIELD = "text"
VECTOR_FIELD = "embedding"
PAGE_FIELD = "page"
SOURCE_FIELD = "source"

# IVF_FLAT index params (COSINE for retrieval alignment)
IVF_NLIST = 128
METRIC_TYPE = "COSINE"


def _ensure_connection() -> None:
    """Connect to Milvus if not already connected."""
    try:
        connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)
    except Exception as e:
        logger.warning("Milvus may already be connected: %s", e)


def get_collection_schema(vector_dim: int) -> CollectionSchema:
    """Build schema for pdf_chunks: id, doc_id, text, embedding, page, source."""
    fields = [
        FieldSchema(PK_FIELD, DataType.VARCHAR, is_primary=True, max_length=64, auto_id=False),
        FieldSchema(DOC_ID_FIELD, DataType.VARCHAR, max_length=64),
        FieldSchema(TEXT_FIELD, DataType.VARCHAR, max_length=65535),
        FieldSchema(VECTOR_FIELD, DataType.FLOAT_VECTOR, dim=vector_dim),
        FieldSchema(PAGE_FIELD, DataType.INT64),
        FieldSchema(SOURCE_FIELD, DataType.VARCHAR, max_length=2048),
    ]
    return CollectionSchema(fields=fields, description="PDF chunks with embeddings")


def ensure_collection(vector_dim: int, recreate: bool = False) -> Collection:
    """
    Create collection if it does not exist; optionally drop and recreate.
    Build IVF_FLAT index on vector field if not present.
    """
    _ensure_connection()
    if recreate and has_collection(COLLECTION_NAME):
        drop_collection(COLLECTION_NAME)
        logger.info("Dropped collection %s", COLLECTION_NAME)

    if not has_collection(COLLECTION_NAME):
        schema = get_collection_schema(vector_dim)
        collection = Collection(name=COLLECTION_NAME, schema=schema)
        logger.info("Created collection %s with dim=%s", COLLECTION_NAME, vector_dim)
    else:
        collection = Collection(COLLECTION_NAME)

    # Create IVF_FLAT index on vector field if no index
    try:
        if not collection.indexes:
            index_params = {
                "index_type": "IVF_FLAT",
                "metric_type": METRIC_TYPE,
                "params": {"nlist": IVF_NLIST},
            }
            collection.create_index(VECTOR_FIELD, index_params)
            logger.info("Created IVF_FLAT index on %s", VECTOR_FIELD)
    except Exception as e:
        if "already exist" in str(e).lower() or "index exist" in str(e).lower():
            pass
        else:
            logger.warning("Index creation: %s", e)

    collection.load()
    return collection


def insert_chunks_batch(
    doc_id: str,
    chunks: list[dict[str, Any]],
    vectors: list[list[float]],
    batch_size: int = 64,
) -> int:
    """
    Insert chunk entities in batches. Each chunk has keys: text, page, source.
    vectors[i] corresponds to chunks[i]. Returns total inserted count.
    """
    if not chunks or len(chunks) != len(vectors):
        return 0

    collection = Collection(COLLECTION_NAME)
    total = 0
    for i in range(0, len(chunks), batch_size):
        batch_chunks = chunks[i : i + batch_size]
        batch_vectors = vectors[i : i + batch_size]
        ids = [str(uuid.uuid4()) for _ in batch_chunks]
        doc_ids = [doc_id] * len(batch_chunks)
        texts = [c["text"] for c in batch_chunks]
        pages = [c.get("page", 0) for c in batch_chunks]
        sources = [c.get("source", "") for c in batch_chunks]
        data = [
            ids,
            doc_ids,
            texts,
            batch_vectors,
            pages,
            sources,
        ]
        collection.insert(data)
        total += len(batch_chunks)
        logger.debug("Inserted batch %s–%s (%s entities)", i, i + len(batch_chunks), len(batch_chunks))

    collection.flush()
    collection.load()  # make new data searchable (e.g. in Attu)
    logger.info("Inserted %s entities for doc_id=%s", total, doc_id)
    return total

