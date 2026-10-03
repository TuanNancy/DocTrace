"""Index PDF bytes: extract pages, split text, embed chunks, and insert into the vector store."""
import logging
import os
import tempfile
from dataclasses import dataclass, field
from starlette.concurrency import run_in_threadpool
from anyio import CancelScope

from app.core.config import get_config
from app.storage.factory import create_connected_vector_store

logger = logging.getLogger(__name__)


@dataclass
class IndexingResult:
    chunks_count: int
    warnings: list[str] = field(default_factory=list)


class InvalidPDFError(ValueError):
    """Permanent input failure: another network retry cannot repair this PDF."""


async def index_pdf_bytes(
    file_content: bytes,
    filename: str,
    doc_id: str,
    *,
    user_id: str,
) -> IndexingResult:
    """Index a PDF under an attempt's generation ID and clean up temporary resources.

    Authentication, HTTP validation, and original-PDF retention belong to the
    caller. doc_id here is the internal generation, not the public library ID.
    """
    from app.processors.pdf import chunk_documents, load_pdf_pages
    from app.providers.embeddings import get_embedder

    if not user_id:
        raise ValueError("Document owner is required.")
    suffix = os.path.splitext(filename)[1] or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(file_content)
        temp_path = f.name

    try:
        try:
            docs, warnings = await run_in_threadpool(load_pdf_pages, temp_path, original_filename=filename)
        except ValueError as exc:
            raise InvalidPDFError("PDF is corrupt or unreadable.") from exc
        chunks = await run_in_threadpool(chunk_documents, docs)
        if not chunks:
            raise InvalidPDFError("No text chunks produced from PDF.")
        config = get_config()
        if len(chunks) > config.max_chunks_per_document:
            raise InvalidPDFError("PDF produces too many chunks. Split it into smaller documents.")

        embedder = await run_in_threadpool(get_embedder, config=config)
        vectors = await run_in_threadpool(embedder.embed_documents, [c["text"] for c in chunks])
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

        vector_store = await create_connected_vector_store(config=config)
        try:
            # Reject incompatible existing collections without deleting their data.
            await vector_store.ensure_collection(vector_dim=vector_dim)
            insert_result = await vector_store.insert_chunks(
                doc_id=doc_id,
                chunks=chunks,
                vectors=vectors,
                user_id=user_id,
            )
        finally:
            with CancelScope(shield=True):
                await vector_store.disconnect()

        merged_warnings = list(warnings or [])
        merged_warnings.extend(insert_result.warnings or [])
        return IndexingResult(
            chunks_count=insert_result.chunks_inserted,
            warnings=merged_warnings,
        )
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
