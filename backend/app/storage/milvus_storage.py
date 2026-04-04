"""
Milvus storage backend implementation.
Implements BaseStorage interface for Milvus vector database operations.
"""
import logging
import uuid
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    drop_collection,
    has_collection,
)

from app.storage.base import BaseStorage, RetrievedChunk, InsertResult

logger = logging.getLogger(__name__)


class MilvusStorage(BaseStorage):
    PK_FIELD = "id"
    DOC_ID_FIELD = "doc_id"
    TEXT_FIELD = "text"
    VECTOR_FIELD = "embedding"
    PAGE_FIELD = "page"
    SOURCE_FIELD = "source"
    CREATED_AT_FIELD = "created_at"
    UPDATED_AT_FIELD = "updated_at"
    STATUS_FIELD = "status"
    METADATA_FIELD = "metadata"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 19530)
        self.collection_name = config.get("collection", "pdf_chunks")
        self.vector_dim = config.get("vector_dim", 1536)
        self.index_type = config.get("index_type", "IVF_FLAT")
        self.metric_type = config.get("metric_type", "COSINE")
        self.nlist = config.get("nlist", 128)
        self.nprobe = config.get("nprobe", 32)
        self._collection: Optional[Collection] = None

    async def connect(self) -> None:
        try:
            if not connections.has_connection("default"):
                connections.connect(alias="default", host=self.host, port=self.port)
                logger.info(f"Connected to Milvus at {self.host}:{self.port}")
            self._connected = True
        except Exception as e:
            logger.exception(f"Failed to connect to Milvus: {e}")
            raise RuntimeError(f"Milvus connection failed: {e}") from e

    async def disconnect(self) -> None:
        try:
            if connections.has_connection("default"):
                connections.disconnect("default")
                logger.info("Disconnected from Milvus")
            self._connected = False
            self._collection = None
        except Exception as e:
            logger.warning(f"Error disconnecting from Milvus: {e}")

    async def is_connected(self) -> bool:
        try:
            return connections.has_connection("default") and self._connected
        except Exception:
            return False

    def _get_collection_schema(self, vector_dim: int) -> CollectionSchema:
        fields = [
            FieldSchema(self.PK_FIELD, DataType.VARCHAR, is_primary=True, max_length=64, auto_id=False),
            FieldSchema(self.DOC_ID_FIELD, DataType.VARCHAR, max_length=64),
            FieldSchema(self.TEXT_FIELD, DataType.VARCHAR, max_length=65535),
            FieldSchema(self.VECTOR_FIELD, DataType.FLOAT_VECTOR, dim=vector_dim),
            FieldSchema(self.PAGE_FIELD, DataType.INT64),
            FieldSchema(self.SOURCE_FIELD, DataType.VARCHAR, max_length=2048),
            FieldSchema(self.CREATED_AT_FIELD, DataType.VARCHAR, max_length=32),
            FieldSchema(self.UPDATED_AT_FIELD, DataType.VARCHAR, max_length=32),
            FieldSchema(self.STATUS_FIELD, DataType.VARCHAR, max_length=32),
            FieldSchema(self.METADATA_FIELD, DataType.VARCHAR, max_length=65535),
        ]
        return CollectionSchema(fields=fields, description=f"PDF chunks with embeddings - {self.collection_name}")

    def _collection_vector_dim(self) -> Optional[int]:
        try:
            if not has_collection(self.collection_name):
                return None
            coll = Collection(self.collection_name)
            for field in coll.schema.fields:
                if field.name != self.VECTOR_FIELD:
                    continue
                params = getattr(field, "params", None) or {}
                dim = params.get("dim")
                if dim is not None:
                    return int(dim)
        except Exception as e:
            logger.warning("Could not read collection schema dim: %s", e)
        return None

    async def ensure_collection(self, vector_dim: int, recreate: bool = False) -> None:
        await self.connect()

        if recreate and has_collection(self.collection_name):
            drop_collection(self.collection_name)
            logger.info(f"Dropped collection {self.collection_name}")

        if not has_collection(self.collection_name):
            schema = self._get_collection_schema(vector_dim)
            collection = Collection(name=self.collection_name, schema=schema)
            logger.info(f"Created collection {self.collection_name} with dim={vector_dim}")
        else:
            existing_dim = self._collection_vector_dim()
            if existing_dim is not None and existing_dim != vector_dim:
                logger.warning(
                    "Collection %s has dim=%s but embeddings require dim=%s; recreating collection.",
                    self.collection_name, existing_dim, vector_dim,
                )
                drop_collection(self.collection_name)
                schema = self._get_collection_schema(vector_dim)
                collection = Collection(name=self.collection_name, schema=schema)
                logger.info("Recreated collection %s with dim=%s", self.collection_name, vector_dim)
            else:
                collection = Collection(self.collection_name)

        try:
            if not collection.indexes:
                index_params = {
                    "index_type": self.index_type,
                    "metric_type": self.metric_type,
                    "params": {"nlist": self.nlist},
                }
                collection.create_index(self.VECTOR_FIELD, index_params)
                logger.info(f"Created {self.index_type} index on {self.VECTOR_FIELD}")
        except Exception as e:
            if "already exist" not in str(e).lower() and "index exist" not in str(e).lower():
                logger.warning(f"Index creation warning: {e}")

        collection.load()
        self._collection = collection

    async def insert_chunks(
        self,
        doc_id: str,
        chunks: List[Dict[str, Any]],
        vectors: List[List[float]],
        batch_size: int = 64
    ) -> InsertResult:
        if not chunks or len(chunks) != len(vectors):
            raise ValueError("Chunks and vectors must be non-empty and of equal length")

        await self.connect()
        await self.ensure_collection(len(vectors[0]))

        collection = Collection(self.collection_name)
        total = 0
        current_time = datetime.utcnow().isoformat()

        for i in range(0, len(chunks), batch_size):
            batch_chunks = chunks[i : i + batch_size]
            batch_vectors = vectors[i : i + batch_size]

            ids = [str(uuid.uuid4()) for _ in batch_chunks]
            doc_ids = [doc_id] * len(batch_chunks)
            texts = [c["text"] for c in batch_chunks]
            pages = [c.get("page", 0) for c in batch_chunks]
            sources = [c.get("source", "") for c in batch_chunks]
            created_ats = [current_time] * len(batch_chunks)
            updated_ats = [current_time] * len(batch_chunks)
            statuses = ["completed"] * len(batch_chunks)
            metadatas = [json.dumps(c.get("metadata", {}), ensure_ascii=False) for c in batch_chunks]

            data = [ids, doc_ids, texts, batch_vectors, pages, sources, created_ats, updated_ats, statuses, metadatas]

            collection.insert(data)
            total += len(batch_chunks)
            logger.debug(f"Inserted batch {i}-{i + len(batch_chunks)} ({len(batch_chunks)} entities)")

        collection.flush()
        collection.load()
        logger.info(f"Inserted {total} entities for doc_id={doc_id}")

        return InsertResult(doc_id=doc_id, chunks_inserted=total, warnings=[])

    async def search_chunks(
        self,
        query_vector: List[float],
        doc_id: Optional[str] = None,
        top_k: int = 8,
        min_score: Optional[float] = None
    ) -> List[RetrievedChunk]:
        if not query_vector:
            return []

        await self.connect()

        try:
            collection = Collection(self.collection_name)
        except Exception as e:
            logger.warning(f"Collection not available: {e}")
            return []

        expr = None
        if doc_id:
            expr = f'{self.DOC_ID_FIELD} == "{doc_id}"'

        search_param = {
            "metric_type": self.metric_type,
            "params": {"nprobe": self.nprobe},
        }

        output_fields = [self.TEXT_FIELD, self.PAGE_FIELD, self.SOURCE_FIELD, self.DOC_ID_FIELD]

        try:
            results = collection.search(
                data=[query_vector],
                anns_field=self.VECTOR_FIELD,
                param=search_param,
                limit=top_k,
                expr=expr,
                output_fields=output_fields,
            )
        except Exception as e:
            logger.exception(f"Search failed: {e}")
            return []

        out: List[RetrievedChunk] = []
        if not results or len(results) == 0:
            return out

        for hit in results[0]:
            entity = hit.get("entity", hit) if isinstance(hit, dict) else getattr(hit, "entity", hit)

            if isinstance(entity, dict):
                text = entity.get(self.TEXT_FIELD) or ""
                page = entity.get(self.PAGE_FIELD, 0) or 0
                source = entity.get(self.SOURCE_FIELD) or ""
                doc_id_result = entity.get(self.DOC_ID_FIELD) or ""
            else:
                text = getattr(entity, self.TEXT_FIELD, "") or ""
                page = getattr(entity, self.PAGE_FIELD, 0) or 0
                source = getattr(entity, self.SOURCE_FIELD, "") or ""
                doc_id_result = getattr(entity, self.DOC_ID_FIELD, "") or ""

            score = float(hit.get("distance", hit.score if hasattr(hit, "score") else 0) or 0.0)

            if min_score is not None and score < min_score:
                continue

            out.append(
                RetrievedChunk(
                    chunk_id=str(uuid.uuid4()),
                    doc_id=str(doc_id_result),
                    text=str(text),
                    page=int(page),
                    source=str(source),
                    score=score,
                )
            )

        logger.info(f"Retrieval: doc_id={doc_id} top_k={top_k} -> {len(out)} hits")
        return out
