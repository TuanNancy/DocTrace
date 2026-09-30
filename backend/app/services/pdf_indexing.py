"""Index PDF bytes: extract pages, split text, embed chunks, and insert into the vector store."""
import logging
import os
import tempfile
import time

from app.models.document import DocumentStatus, IndexingResult, create_indexing_result
from app.storage.factory import create_connected_vector_store

logger = logging.getLogger(__name__)


async def index_pdf_bytes(
    file_content: bytes,
    filename: str,
    doc_id: str,
) -> IndexingResult:
    """Index a PDF under an existing document ID and clean up temporary resources.

    Authentication, HTTP validation, and original-PDF retention belong to the
    caller. The document ID is shared by the stored PDF and all indexed chunks.
    """
    from app.processors.pdf import chunk_documents, load_pdf_pages
    from app.providers.embeddings import get_embedder

    start_time = time.time()
    suffix = os.path.splitext(filename)[1] or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(file_content)
        temp_path = f.name

    try:
        docs, warnings = load_pdf_pages(temp_path, original_filename=filename)
        chunks = chunk_documents(docs)
        if not chunks:
            raise ValueError("No text chunks produced from PDF.")

        embedder = get_embedder()
        vectors = embedder.embed_documents([c["text"] for c in chunks])
        if len(vectors) != len(chunks):
            raise RuntimeError("Embedding count does not match chunk count.")
        if not vectors or not vectors[0]:
            raise RuntimeError("Embedding API returned empty vectors.")

        # Use the actual response dimension, rather than a configured or probed default.
        vector_dim = len(vectors[0])
        if embedder.dimension != vector_dim:
            logger.warning(
                "Embedder.dimension=%s differs from actual vector length=%s; using vector length for Milvus.",
                embedder.dimension,
                vector_dim,
            )

        vector_store = await create_connected_vector_store()
        try:
            # Reject incompatible existing collections without deleting their data.
            await vector_store.ensure_collection(vector_dim=vector_dim)
            insert_result = await vector_store.insert_chunks(
                doc_id=doc_id,
                chunks=chunks,
                vectors=vectors,
            )
        finally:
            await vector_store.disconnect()

        merged_warnings = list(warnings or [])
        merged_warnings.extend(insert_result.warnings or [])
        return create_indexing_result(
            doc_id=doc_id,
            name=filename,
            chunks_count=insert_result.chunks_inserted,
            status=DocumentStatus.COMPLETED,
            processing_time=time.time() - start_time,
            warnings=merged_warnings,
        )
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
