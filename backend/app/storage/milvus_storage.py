"""
Milvus storage backend implementation.
Implements BaseStorage interface for Milvus vector database operations.
"""
import logging
import uuid
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
    utility,
)

from app.storage.base import BaseStorage, DocumentMetadata, RetrievedChunk, InsertResult

logger = logging.getLogger(__name__)


class MilvusStorage(BaseStorage):
    """
    Milvus storage backend implementation.

    This class provides a complete implementation of the BaseStorage interface
    using Milvus as the vector database backend. It handles connection management,
    collection creation, chunk insertion, and vector search operations.
    """

    # Collection field names
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
        """
        Initialize Milvus storage backend.

        Args:
            config: Configuration dictionary with keys:
                - host: Milvus server host (default: "localhost")
                - port: Milvus server port (default: 19530)
                - collection: Collection name (default: "pdf_chunks")
                - vector_dim: Vector dimension (default: 1536)
                - index_type: Index type (default: "IVF_FLAT")
                - metric_type: Metric type (default: "COSINE")
                - nlist: IVF nlist parameter (default: 128)
                - nprobe: Search nprobe parameter (default: 32)
        """
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
        """
        Establish connection to Milvus server.

        Creates a connection alias "default" if not already connected.
        """
        try:
            if not connections.has_connection("default"):
                connections.connect(
                    alias="default",
                    host=self.host,
                    port=self.port,
                )
                logger.info(f"Connected to Milvus at {self.host}:{self.port}")
            self._connected = True
        except Exception as e:
            logger.exception(f"Failed to connect to Milvus: {e}")
            raise RuntimeError(f"Milvus connection failed: {e}") from e

    async def disconnect(self) -> None:
        """
        Close connection to Milvus server.

        Disconnects from Milvus and cleans up resources.
        """
        try:
            if connections.has_connection("default"):
                connections.disconnect("default")
                logger.info("Disconnected from Milvus")
            self._connected = False
            self._collection = None
        except Exception as e:
            logger.warning(f"Error disconnecting from Milvus: {e}")

    async def is_connected(self) -> bool:
        """
        Check if connected to Milvus.

        Returns:
            True if connected, False otherwise
        """
        try:
            return connections.has_connection("default") and self._connected
        except Exception:
            return False

    def _get_collection_schema(self, vector_dim: int) -> CollectionSchema:
        """
        Build schema for PDF chunks collection.

        Args:
            vector_dim: Dimension of the embedding vectors

        Returns:
            CollectionSchema object
        """
        fields = [
            FieldSchema(
                self.PK_FIELD,
                DataType.VARCHAR,
                is_primary=True,
                max_length=64,
                auto_id=False,
            ),
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
        return CollectionSchema(
            fields=fields,
            description=f"PDF chunks with embeddings - {self.collection_name}",
        )

    async def ensure_collection(
        self,
        vector_dim: int,
        recreate: bool = False
    ) -> None:
        """
        Ensure that the collection exists and is properly configured.

        Args:
            vector_dim: Dimension of the vectors to be stored
            recreate: If True, drop and recreate the collection
        """
        await self.connect()

        if recreate and has_collection(self.collection_name):
            drop_collection(self.collection_name)
            logger.info(f"Dropped collection {self.collection_name}")

        if not has_collection(self.collection_name):
            schema = self._get_collection_schema(vector_dim)
            collection = Collection(name=self.collection_name, schema=schema)
            logger.info(
                f"Created collection {self.collection_name} with dim={vector_dim}"
            )
        else:
            collection = Collection(self.collection_name)

        # Create index on vector field if not present
        try:
            if not collection.indexes:
                index_params = {
                    "index_type": self.index_type,
                    "metric_type": self.metric_type,
                    "params": {"nlist": self.nlist},
                }
                collection.create_index(self.VECTOR_FIELD, index_params)
                logger.info(
                    f"Created {self.index_type} index on {self.VECTOR_FIELD}"
                )
        except Exception as e:
            if "already exist" in str(e).lower() or "index exist" in str(e).lower():
                pass
            else:
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
        """
        Insert document chunks with their embeddings into Milvus.

        Args:
            doc_id: Unique document identifier
            chunks: List of chunk dictionaries with keys: text, page, source
            vectors: List of embedding vectors corresponding to chunks
            batch_size: Number of chunks to insert per batch

        Returns:
            InsertResult with doc_id, chunks_inserted, and warnings
        """
        if not chunks or len(chunks) != len(vectors):
            raise ValueError("Chunks and vectors must be non-empty and of equal length")

        await self.connect()
        await self.ensure_collection(len(vectors[0]))

        collection = Collection(self.collection_name)
        total = 0
        warnings = []

        current_time = datetime.utcnow().isoformat()

        for i in range(0, len(chunks), batch_size):
            batch_chunks = chunks[i : i + batch_size]
            batch_vectors = vectors[i : i + batch_size]

            # Prepare data for insertion
            ids = [str(uuid.uuid4()) for _ in batch_chunks]
            doc_ids = [doc_id] * len(batch_chunks)
            texts = [c["text"] for c in batch_chunks]
            pages = [c.get("page", 0) for c in batch_chunks]
            sources = [c.get("source", "") for c in batch_chunks]
            created_ats = [current_time] * len(batch_chunks)
            updated_ats = [current_time] * len(batch_chunks)
            statuses = ["completed"] * len(batch_chunks)
            metadatas = [str(c.get("metadata", {})) for c in batch_chunks]

            data = [
                ids,
                doc_ids,
                texts,
                batch_vectors,
                pages,
                sources,
                created_ats,
                updated_ats,
                statuses,
                metadatas,
            ]

            collection.insert(data)
            total += len(batch_chunks)
            logger.debug(
                f"Inserted batch {i}-{i + len(batch_chunks)} "
                f"({len(batch_chunks)} entities)"
            )

        collection.flush()
        collection.load()

        logger.info(f"Inserted {total} entities for doc_id={doc_id}")

        return InsertResult(
            doc_id=doc_id,
            chunks_inserted=total,
            warnings=warnings,
        )

    async def search_chunks(
        self,
        query_vector: List[float],
        doc_id: Optional[str] = None,
        top_k: int = 8,
        min_score: Optional[float] = None
    ) -> List[RetrievedChunk]:
        """
        Search for similar chunks using vector similarity.

        Args:
            query_vector: Query embedding vector
            doc_id: Optional document ID to filter results
            top_k: Maximum number of results to return
            min_score: Minimum relevance score threshold

        Returns:
            List of RetrievedChunk objects sorted by relevance
        """
        if not query_vector:
            return []

        await self.connect()

        try:
            collection = Collection(self.collection_name)
        except Exception as e:
            logger.warning(f"Collection not available: {e}")
            return []

        # Build expression filter
        expr = None
        if doc_id:
            expr = f'{self.DOC_ID_FIELD} == "{doc_id}"'

        # Search parameters
        search_param = {
            "metric_type": self.metric_type,
            "params": {"nprobe": self.nprobe},
        }

        output_fields = [
            self.TEXT_FIELD,
            self.PAGE_FIELD,
            self.SOURCE_FIELD,
            self.DOC_ID_FIELD,
        ]

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
            # Extract entity data
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

            # Get score (distance)
            score = float(
                hit.get("distance", hit.score if hasattr(hit, "score") else 0) or 0.0
            )

            # Apply minimum score filter
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

        logger.info(
            f"Retrieval: doc_id={doc_id} top_k={top_k} -> {len(out)} hits"
        )

        return out

    async def get_document_metadata(
        self,
        doc_id: str
    ) -> Optional[DocumentMetadata]:
        """
        Get metadata for a specific document.

        Args:
            doc_id: Document identifier

        Returns:
            DocumentMetadata or None if not found
        """
        await self.connect()

        try:
            collection = Collection(self.collection_name)
        except Exception as e:
            logger.warning(f"Collection not available: {e}")
            return None

        # Query for document metadata
        expr = f'{self.DOC_ID_FIELD} == "{doc_id}"'
        try:
            results = collection.query(
                expr=expr,
                output_fields=[
                    self.DOC_ID_FIELD,
                    self.CREATED_AT_FIELD,
                    self.UPDATED_AT_FIELD,
                    self.STATUS_FIELD,
                    self.METADATA_FIELD,
                ],
                limit=1,
            )

            if not results:
                return None

            result = results[0]
            chunks_count = await self.count_chunks(doc_id)

            return DocumentMetadata(
                doc_id=result.get(self.DOC_ID_FIELD, doc_id),
                name=result.get(self.SOURCE_FIELD, "Unknown"),
                chunks_count=chunks_count,
                created_at=datetime.fromisoformat(
                    result.get(self.CREATED_AT_FIELD, datetime.utcnow().isoformat())
                ),
                updated_at=datetime.fromisoformat(
                    result.get(self.UPDATED_AT_FIELD)
                ) if result.get(self.UPDATED_AT_FIELD) else None,
                status=result.get(self.STATUS_FIELD, "unknown"),
                metadata=eval(result.get(self.METADATA_FIELD, "{}"))
                if result.get(self.METADATA_FIELD)
                else {},
            )

        except Exception as e:
            logger.exception(f"Failed to get document metadata: {e}")
            return None

    async def list_documents(
        self,
        limit: int = 100,
        offset: int = 0
    ) -> List[DocumentMetadata]:
        """
        List all documents in storage.

        Args:
            limit: Maximum number of documents to return
            offset: Number of documents to skip

        Returns:
            List of DocumentMetadata objects
        """
        await self.connect()

        try:
            collection = Collection(self.collection_name)
        except Exception as e:
            logger.warning(f"Collection not available: {e}")
            return []

        try:
            # Query all unique doc_ids
            results = collection.query(
                expr="",
                output_fields=[self.DOC_ID_FIELD],
                limit=limit * 10,  # Get more to deduplicate
            )

            # Deduplicate doc_ids
            unique_doc_ids = list({r.get(self.DOC_ID_FIELD) for r in results if r.get(self.DOC_ID_FIELD)})
            unique_doc_ids = unique_doc_ids[offset:offset + limit]

            # Get metadata for each document
            documents = []
            for doc_id in unique_doc_ids:
                metadata = await self.get_document_metadata(doc_id)
                if metadata:
                    documents.append(metadata)

            return documents

        except Exception as e:
            logger.exception(f"Failed to list documents: {e}")
            return []

    async def delete_document(
        self,
        doc_id: str
    ) -> bool:
        """
        Delete a document and all its chunks from Milvus.

        Args:
            doc_id: Document identifier

        Returns:
            True if deleted successfully, False otherwise
        """
        await self.connect()

        try:
            collection = Collection(self.collection_name)

            # Delete all chunks for this document
            expr = f'{self.DOC_ID_FIELD} == "{doc_id}"'
            collection.delete(expr)

            collection.flush()
            logger.info(f"Deleted document {doc_id}")

            return True

        except Exception as e:
            logger.exception(f"Failed to delete document {doc_id}: {e}")
            return False

    async def search_documents(
        self,
        query: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search for documents by metadata (not vector search).

        Args:
            query: Search query string (searches in source field)
            limit: Maximum number of results

        Returns:
            List of document metadata dictionaries
        """
        await self.connect()

        try:
            collection = Collection(self.collection_name)
        except Exception as e:
            logger.warning(f"Collection not available: {e}")
            return []

        try:
            # Search in source field
            expr = f'{self.SOURCE_FIELD} like "%{query}%"'
            results = collection.query(
                expr=expr,
                output_fields=[
                    self.DOC_ID_FIELD,
                    self.SOURCE_FIELD,
                    self.CREATED_AT_FIELD,
                    self.STATUS_FIELD,
                ],
                limit=limit,
            )

            # Deduplicate by doc_id
            seen = set()
            documents = []
            for result in results:
                doc_id = result.get(self.DOC_ID_FIELD)
                if doc_id and doc_id not in seen:
                    seen.add(doc_id)
                    documents.append({
                        "doc_id": doc_id,
                        "name": result.get(self.SOURCE_FIELD, ""),
                        "created_at": result.get(self.CREATED_AT_FIELD, ""),
                        "status": result.get(self.STATUS_FIELD, ""),
                    })

            return documents

        except Exception as e:
            logger.exception(f"Failed to search documents: {e}")
            return []

    async def get_document_chunks(
        self,
        doc_id: str,
        page: Optional[int] = None
    ) -> List[RetrievedChunk]:
        """
        Get all chunks for a specific document.

        Args:
            doc_id: Document identifier
            page: Optional page number to filter chunks

        Returns:
            List of RetrievedChunk objects
        """
        await self.connect()

        try:
            collection = Collection(self.collection_name)
        except Exception as e:
            logger.warning(f"Collection not available: {e}")
            return []

        try:
            # Build expression
            expr = f'{self.DOC_ID_FIELD} == "{doc_id}"'
            if page is not None:
                expr += f' && {self.PAGE_FIELD} == {page}'

            results = collection.query(
                expr=expr,
                output_fields=[
                    self.TEXT_FIELD,
                    self.PAGE_FIELD,
                    self.SOURCE_FIELD,
                    self.DOC_ID_FIELD,
                ],
            )

            chunks = []
            for result in results:
                chunks.append(
                    RetrievedChunk(
                        chunk_id=str(uuid.uuid4()),
                        doc_id=result.get(self.DOC_ID_FIELD, doc_id),
                        text=result.get(self.TEXT_FIELD, ""),
                        page=result.get(self.PAGE_FIELD, 0),
                        source=result.get(self.SOURCE_FIELD, ""),
                        score=1.0,  # Perfect match for direct retrieval
                    )
                )

            return chunks

        except Exception as e:
            logger.exception(f"Failed to get document chunks: {e}")
            return []

    async def count_chunks(
        self,
        doc_id: Optional[str] = None
    ) -> int:
        """
        Count total chunks in storage.

        Args:
            doc_id: Optional document ID to count chunks for specific document

        Returns:
            Total number of chunks
        """
        await self.connect()

        try:
            collection = Collection(self.collection_name)
        except Exception as e:
            logger.warning(f"Collection not available: {e}")
            return 0

        try:
            expr = f'{self.DOC_ID_FIELD} == "{doc_id}"' if doc_id else ""
            results = collection.query(
                expr=expr,
                output_fields=[self.PK_FIELD],
            )
            return len(results)

        except Exception as e:
            logger.exception(f"Failed to count chunks: {e}")
            return 0

    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on Milvus storage.

        Returns:
            Dictionary with health status information
        """
        try:
            base_health = await super().health_check()

            if not base_health.get("connected"):
                return base_health

            # Additional Milvus-specific checks
            collection_exists = has_collection(self.collection_name)

            return {
                **base_health,
                "collection_exists": collection_exists,
                "collection_name": self.collection_name,
                "host": self.host,
                "port": self.port,
            }

        except Exception as e:
            logger.exception("Health check failed: %s", e)
            return {
                "status": "unhealthy",
                "connected": False,
                "backend": self.__class__.__name__,
                "error": str(e),
            }

    async def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about Milvus storage.

        Returns:
            Dictionary with storage statistics
        """
        try:
            base_stats = await super().get_stats()

            if not base_stats.get("total_documents"):
                return base_stats

            # Additional Milvus-specific stats
            collection_exists = has_collection(self.collection_name)

            return {
                **base_stats,
                "collection_exists": collection_exists,
                "collection_name": self.collection_name,
                "vector_dim": self.vector_dim,
                "index_type": self.index_type,
                "metric_type": self.metric_type,
            }

        except Exception as e:
            logger.exception("Failed to get stats: %s", e)
            return {
                "total_documents": 0,
                "total_chunks": 0,
                "backend": self.__class__.__name__,
                "error": str(e),
            }
