"""Indexing service behavior with external embedding and vector store calls isolated."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document

from app.processors import pdf
from app.providers import embeddings
from app.services import pdf_indexing
from app.storage.base import InsertResult, VectorStore


@pytest.fixture
def indexing_dependencies(monkeypatch):
    temporary_paths = []

    def load_pages(path, *, original_filename):
        assert Path(path).read_bytes() == b"pdf contents"
        temporary_paths.append(Path(path))
        return [Document(page_content="Twelve days of annual leave.", metadata={"page": 2, "source": original_filename})], ["PDF warning"]

    monkeypatch.setattr(pdf, "load_pdf_pages", load_pages)
    monkeypatch.setattr(pdf, "get_config", lambda: SimpleNamespace(chunk_size=1000, chunk_overlap=150))
    monkeypatch.setattr(pdf_indexing, "get_config", lambda: SimpleNamespace(max_chunks_per_document=2000))
    embedder = MagicMock()
    embedder.dimension = 1536  # The real response dimension must take precedence.
    embedder.embed_documents.return_value = [[0.1, 0.2, 0.3]]
    monkeypatch.setattr(embeddings, "get_embedder", lambda **kwargs: embedder)
    vector_store = AsyncMock(spec=VectorStore)
    vector_store.insert_chunks.return_value = InsertResult("doc-1", 1, ["Store warning"])
    factory = AsyncMock(return_value=vector_store)
    monkeypatch.setattr(pdf_indexing, "create_connected_vector_store", factory)
    return SimpleNamespace(
        temporary_paths=temporary_paths,
        embedder=embedder,
        vector_store=vector_store,
        factory=factory,
    )


async def test_indexing_preserves_metadata_warnings_and_actual_dimension(indexing_dependencies):
    deps = indexing_dependencies
    result = await pdf_indexing.index_pdf_bytes(b"pdf contents", "policy.pdf", "doc-1", user_id="user-a")

    assert result.chunks_count == 1
    assert result.warnings == ["PDF warning", "Store warning"]
    deps.vector_store.ensure_collection.assert_awaited_once_with(vector_dim=3)
    chunks = deps.vector_store.insert_chunks.call_args.kwargs["chunks"]
    assert deps.vector_store.insert_chunks.call_args.kwargs["doc_id"] == "doc-1"
    assert deps.vector_store.insert_chunks.call_args.kwargs["user_id"] == "user-a"
    assert chunks[0]["page"] == 2
    assert chunks[0]["source"] == "policy.pdf"
    deps.vector_store.disconnect.assert_awaited_once()
    assert deps.temporary_paths and all(not path.exists() for path in deps.temporary_paths)


@pytest.mark.parametrize("failure_stage", ["embedding", "schema", "insert"])
async def test_indexing_cleans_up_resources_on_failure(indexing_dependencies, failure_stage):
    deps = indexing_dependencies
    failure = RuntimeError("upstream failure")
    if failure_stage == "embedding":
        deps.embedder.embed_documents.side_effect = failure
    elif failure_stage == "schema":
        deps.vector_store.ensure_collection.side_effect = failure
    else:
        deps.vector_store.insert_chunks.side_effect = failure

    with pytest.raises(RuntimeError, match="upstream failure"):
        await pdf_indexing.index_pdf_bytes(b"pdf contents", "policy.pdf", "doc-1", user_id="user-a")

    assert deps.temporary_paths and all(not path.exists() for path in deps.temporary_paths)
    if failure_stage == "embedding":
        deps.factory.assert_not_awaited()
    else:
        deps.vector_store.disconnect.assert_awaited_once()
    if failure_stage == "schema":
        deps.vector_store.insert_chunks.assert_not_awaited()


@pytest.mark.parametrize("vectors", [[], [[]]])
async def test_invalid_embeddings_never_reach_vector_store(indexing_dependencies, vectors):
    deps = indexing_dependencies
    deps.embedder.embed_documents.return_value = vectors
    with pytest.raises(RuntimeError, match="Embedding"):
        await pdf_indexing.index_pdf_bytes(b"pdf contents", "policy.pdf", "doc-1", user_id="user-a")
    deps.factory.assert_not_awaited()
    assert deps.temporary_paths and all(not path.exists() for path in deps.temporary_paths)


async def test_chunk_limit_prevents_embedding_spend(indexing_dependencies, monkeypatch):
    monkeypatch.setattr(pdf_indexing, "get_config", lambda: SimpleNamespace(max_chunks_per_document=0))
    with pytest.raises(ValueError, match="too many chunks"):
        await pdf_indexing.index_pdf_bytes(b"pdf contents", "policy.pdf", "doc-1", user_id="user-a")
    indexing_dependencies.embedder.embed_documents.assert_not_called()
    indexing_dependencies.factory.assert_not_awaited()
    assert all(not path.exists() for path in indexing_dependencies.temporary_paths)
