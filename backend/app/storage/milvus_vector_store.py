"""Milvus/Zilliz adapter with owner-scoped queries and request-owned connections."""
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, drop_collection, has_collection
from starlette.concurrency import run_in_threadpool

from app.core.config import AppConfig
from app.storage.base import InsertResult, RetrievedChunk, VectorStore

logger = logging.getLogger(__name__)


class MilvusVectorStore(VectorStore):
    PK_FIELD = "id"
    DOC_ID_FIELD = "doc_id"
    USER_ID_FIELD = "user_id"
    TEXT_FIELD = "text"
    VECTOR_FIELD = "embedding"
    PAGE_FIELD = "page"
    SOURCE_FIELD = "source"
    CREATED_AT_FIELD = "created_at"
    UPDATED_AT_FIELD = "updated_at"
    STATUS_FIELD = "status"
    METADATA_FIELD = "metadata"

    def __init__(self, config: AppConfig):
        super().__init__(config)
        self.host = config.milvus_host
        self.port = config.milvus_port
        self.uri = config.milvus_uri
        self.token = config.milvus_token
        self.collection_name = config.milvus_collection
        self.index_type = config.milvus_index_type
        self.metric_type = config.milvus_metric_type
        self.nlist = config.milvus_nlist
        self.nprobe = config.milvus_nprobe
        self.alias = f"doctrace_{uuid.uuid4().hex}"
        self._collection: Optional[Collection] = None

    def _connect(self) -> None:
        if self._connected:
            return
        kwargs = {"alias": self.alias}
        if self.uri:
            kwargs.update(uri=self.uri, token=self.token or "", secure=self.uri.startswith("https://"))
        else:
            kwargs.update(host=self.host, port=self.port)
        try:
            connections.connect(**kwargs)
            self._connected = True
        except Exception:
            connections.remove_connection(self.alias)
            raise

    async def connect(self) -> None:
        await run_in_threadpool(self._connect)

    def _disconnect(self) -> None:
        try:
            # remove_connection also disconnects and removes cached alias config.
            connections.remove_connection(self.alias)
        finally:
            self._connected = False
            self._collection = None

    async def disconnect(self) -> None:
        await run_in_threadpool(self._disconnect)

    async def is_connected(self) -> bool:
        return self._connected and connections.has_connection(self.alias)

    def _get_collection_schema(self, vector_dim: int) -> CollectionSchema:
        return CollectionSchema(fields=[
            FieldSchema(self.PK_FIELD, DataType.VARCHAR, is_primary=True, max_length=64, auto_id=False),
            FieldSchema(self.DOC_ID_FIELD, DataType.VARCHAR, max_length=64),
            FieldSchema(self.USER_ID_FIELD, DataType.VARCHAR, max_length=64),
            FieldSchema(self.TEXT_FIELD, DataType.VARCHAR, max_length=65535),
            FieldSchema(self.VECTOR_FIELD, DataType.FLOAT_VECTOR, dim=vector_dim),
            FieldSchema(self.PAGE_FIELD, DataType.INT64),
            FieldSchema(self.SOURCE_FIELD, DataType.VARCHAR, max_length=2048),
            FieldSchema(self.CREATED_AT_FIELD, DataType.VARCHAR, max_length=32),
            FieldSchema(self.UPDATED_AT_FIELD, DataType.VARCHAR, max_length=32),
            FieldSchema(self.STATUS_FIELD, DataType.VARCHAR, max_length=32),
            FieldSchema(self.METADATA_FIELD, DataType.VARCHAR, max_length=65535),
        ], description="Owner-scoped PDF chunks")

    def _ensure_collection(self, vector_dim: int) -> None:
        if vector_dim <= 0:
            raise ValueError("Vector dimension must be positive.")
        self._connect()
        if not has_collection(self.collection_name, using=self.alias):
            collection = Collection(
                name=self.collection_name, schema=self._get_collection_schema(vector_dim), using=self.alias,
            )
        else:
            collection = Collection(self.collection_name, using=self.alias)
            fields = {field.name: field for field in collection.schema.fields}
            field = fields.get(self.VECTOR_FIELD)
            dim = (getattr(field, "params", None) or {}).get("dim")
            if dim is None:
                raise RuntimeError(f"Could not verify vector dimension of collection {self.collection_name!r}.")
            if int(dim) != vector_dim:
                raise RuntimeError(
                    f"Collection {self.collection_name!r} has dimension {dim}, but embeddings have dimension {vector_dim}. "
                    "Use a compatible model or a new collection; recreate_collection() deletes existing chunks."
                )
            owner_field = fields.get(self.USER_ID_FIELD)
            if owner_field is None or owner_field.dtype != DataType.VARCHAR:
                raise RuntimeError("Collection lacks a VARCHAR user_id field. Use a new collection and re-upload PDFs.")

        if not collection.indexes:
            params = {"nlist": self.nlist} if self.index_type.startswith("IVF") else {}
            collection.create_index(self.VECTOR_FIELD, {
                "index_type": self.index_type, "metric_type": self.metric_type, "params": params,
            })
        collection.load()
        self._collection = collection

    async def ensure_collection(self, vector_dim: int) -> None:
        await run_in_threadpool(self._ensure_collection, vector_dim)

    def _recreate_collection(self, vector_dim: int) -> None:
        if vector_dim <= 0:
            raise ValueError("Vector dimension must be positive.")
        self._connect()
        if has_collection(self.collection_name, using=self.alias):
            drop_collection(self.collection_name, using=self.alias)
        self._collection = None
        self._ensure_collection(vector_dim)

    async def recreate_collection(self, vector_dim: int) -> None:
        await run_in_threadpool(self._recreate_collection, vector_dim)

    def _insert_chunks(self, doc_id, chunks, vectors, batch_size, user_id) -> InsertResult:
        if not user_id or not doc_id:
            raise ValueError("Document owner and ID are required.")
        if not chunks or len(chunks) != len(vectors) or not vectors[0] or batch_size <= 0:
            raise ValueError("Chunks/vectors must be non-empty and equal in length; batch size must be positive.")
        self._ensure_collection(len(vectors[0]))
        collection = self._collection
        timestamp = datetime.utcnow().isoformat()
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            count = len(batch)
            collection.insert([
                [str(uuid.uuid4()) for _ in batch], [doc_id] * count, [user_id] * count,
                [chunk["text"] for chunk in batch], vectors[i:i + batch_size],
                [chunk.get("page", 0) for chunk in batch], [chunk.get("source", "") for chunk in batch],
                [timestamp] * count, [timestamp] * count, ["completed"] * count,
                [json.dumps({**chunk.get("metadata", {}), "chunk_index": i + offset}, ensure_ascii=False)
                 for offset, chunk in enumerate(batch)],
            ])
        collection.flush()
        return InsertResult(doc_id=doc_id, chunks_inserted=len(chunks), warnings=[])

    async def insert_chunks(
        self, doc_id: str, chunks: List[Dict[str, Any]], vectors: List[List[float]],
        batch_size: int = 64, *, user_id: str,
    ) -> InsertResult:
        return await run_in_threadpool(self._insert_chunks, doc_id, chunks, vectors, batch_size, user_id)

    def _get_document_chunks(self, doc_id: str, user_id: str) -> List[RetrievedChunk]:
        if not user_id or not doc_id:
            raise ValueError("Document owner and ID are required.")
        self._connect()
        if not has_collection(self.collection_name, using=self.alias):
            return []
        collection = Collection(self.collection_name, using=self.alias)
        expr = f"{self.USER_ID_FIELD} == {json.dumps(user_id)} and {self.DOC_ID_FIELD} == {json.dumps(doc_id)}"
        iterator = collection.query_iterator(
            expr=expr, batch_size=256, consistency_level="Strong",
            output_fields=[self.PK_FIELD, self.DOC_ID_FIELD, self.TEXT_FIELD,
                           self.PAGE_FIELD, self.SOURCE_FIELD, self.METADATA_FIELD],
        )
        chunks = []
        try:
            while True:
                rows = iterator.next()
                if not rows:
                    break
                for row in rows:
                    metadata = json.loads(row.get(self.METADATA_FIELD) or "{}")
                    chunks.append(RetrievedChunk(
                        chunk_id=row[self.PK_FIELD], doc_id=row[self.DOC_ID_FIELD],
                        text=row[self.TEXT_FIELD], page=row.get(self.PAGE_FIELD, 0),
                        source=row.get(self.SOURCE_FIELD, ""), score=None, metadata=metadata,
                    ))
        finally:
            iterator.close()
        # Older uploads have no chunk_index; retain stable ordering within each page.
        return sorted(chunks, key=lambda chunk: (
            chunk.page, chunk.metadata.get("chunk_index", 0), chunk.chunk_id,
        ))

    async def get_document_chunks(self, doc_id: str, *, user_id: str) -> List[RetrievedChunk]:
        return await run_in_threadpool(self._get_document_chunks, doc_id, user_id)

    def _get_chunk(self, doc_id: str, chunk_id: str, user_id: str) -> Optional[RetrievedChunk]:
        if not user_id or not doc_id or not chunk_id:
            raise ValueError("Document owner, ID and chunk ID are required.")
        self._connect()
        if not has_collection(self.collection_name, using=self.alias):
            return None
        collection = Collection(self.collection_name, using=self.alias)
        rows = collection.query(
            expr=f"user_id == {json.dumps(user_id)} and doc_id == {json.dumps(doc_id)} and id == {json.dumps(chunk_id)}",
            output_fields=[self.PK_FIELD, self.TEXT_FIELD, self.PAGE_FIELD, self.SOURCE_FIELD],
            consistency_level="Strong", limit=1,
        )
        if not rows:
            return None
        row = rows[0]
        return RetrievedChunk(row["id"], doc_id, row["text"], row["page"], row["source"], None)

    async def get_chunk(self, doc_id: str, chunk_id: str, *, user_id: str) -> Optional[RetrievedChunk]:
        return await run_in_threadpool(self._get_chunk, doc_id, chunk_id, user_id)

    def _delete_document(self, doc_id: str, user_id: str) -> None:
        if not user_id or not doc_id:
            raise ValueError("Document owner and ID are required.")
        self._connect()
        if has_collection(self.collection_name, using=self.alias):
            collection = Collection(self.collection_name, using=self.alias)
            collection.delete(expr=f"user_id == {json.dumps(user_id)} and doc_id == {json.dumps(doc_id)}")
            collection.flush()

    async def delete_document(self, doc_id: str, *, user_id: str) -> None:
        await run_in_threadpool(self._delete_document, doc_id, user_id)

    def _search_chunks(self, query_vector, doc_id, top_k, min_score, user_id) -> List[RetrievedChunk]:
        if not user_id:
            raise ValueError("Document owner is required.")
        if not query_vector:
            return []
        self._connect()
        collection = Collection(self.collection_name, using=self.alias)
        # JSON quoting escapes user input; ownership is always part of the filter.
        expr = f"{self.USER_ID_FIELD} == {json.dumps(user_id)}"
        if doc_id:
            expr += f" and {self.DOC_ID_FIELD} == {json.dumps(doc_id)}"
        params = {"nprobe": self.nprobe} if self.index_type.startswith("IVF") else {}
        results = collection.search(
            data=[query_vector], anns_field=self.VECTOR_FIELD,
            param={"metric_type": self.metric_type, "params": params}, limit=top_k, expr=expr,
            output_fields=[self.TEXT_FIELD, self.PAGE_FIELD, self.SOURCE_FIELD, self.DOC_ID_FIELD],
            # Make a newly uploaded PDF searchable across request-owned connections.
            consistency_level="Strong",
        )
        out = []
        if not results:
            return out
        for hit in results[0]:
            entity = hit.get("entity", hit) if isinstance(hit, dict) else getattr(hit, "entity", hit)
            chunk_id = hit[self.PK_FIELD] if isinstance(hit, dict) else hit.id
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
            score = float(hit.get("distance", hit.get("score", 0.0)) if isinstance(hit, dict) else hit.score)
            if min_score is None or score >= min_score:
                out.append(RetrievedChunk(str(chunk_id), str(doc_id_result), str(text), int(page), str(source), score))
        return out

    async def search_chunks(
        self, query_vector: List[float], doc_id: Optional[str] = None,
        *, top_k: int, min_score: Optional[float], user_id: str,
    ) -> List[RetrievedChunk]:
        return await run_in_threadpool(self._search_chunks, query_vector, doc_id, top_k, min_score, user_id)
