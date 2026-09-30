"""Vector store regressions: collection preservation and persistent retrieval IDs."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pymilvus.client.search_result import Hit

from app.storage import milvus_vector_store as milvus


@pytest.fixture
def milvus_backend(monkeypatch):
    connections = MagicMock()
    collection = MagicMock()
    collection.schema.fields = [SimpleNamespace(name="embedding", params={"dim": 3})]
    collection.indexes = ["existing-index"]
    collection_factory = MagicMock(return_value=collection)
    has_collection = MagicMock(return_value=True)
    drop_collection = MagicMock()
    monkeypatch.setattr(milvus, "connections", connections)
    monkeypatch.setattr(milvus, "Collection", collection_factory)
    monkeypatch.setattr(milvus, "has_collection", has_collection)
    monkeypatch.setattr(milvus, "drop_collection", drop_collection)
    return SimpleNamespace(
        store=milvus.MilvusVectorStore({"collection": "test_chunks"}),
        collection=collection,
        collection_factory=collection_factory,
        has_collection=has_collection,
        drop_collection=drop_collection,
        connections=connections,
    )


async def test_ensure_collection_preserves_compatible_collection(milvus_backend):
    backend = milvus_backend
    await backend.store.ensure_collection(vector_dim=3)

    backend.drop_collection.assert_not_called()
    assert all("schema" not in call.kwargs for call in backend.collection_factory.call_args_list)
    backend.collection.load.assert_called_once()


@pytest.mark.parametrize("operation", ["ensure", "insert"])
async def test_dimension_mismatch_never_drops_or_inserts(milvus_backend, operation):
    backend = milvus_backend
    with pytest.raises(RuntimeError, match="has dimension 3, but embeddings have dimension 2"):
        if operation == "ensure":
            await backend.store.ensure_collection(vector_dim=2)
        else:
            await backend.store.insert_chunks(
                doc_id="doc-1", chunks=[{"text": "example"}], vectors=[[0.1, 0.2]]
            )

    backend.drop_collection.assert_not_called()
    backend.collection.insert.assert_not_called()
    backend.collection.load.assert_not_called()


async def test_unreadable_schema_is_rejected_without_dropping(milvus_backend):
    backend = milvus_backend
    backend.collection.schema.fields = []
    with pytest.raises(RuntimeError, match="Could not verify vector dimension"):
        await backend.store.ensure_collection(vector_dim=3)

    backend.drop_collection.assert_not_called()
    backend.collection.load.assert_not_called()


async def test_ensure_collection_creates_missing_collection(milvus_backend):
    backend = milvus_backend
    backend.has_collection.return_value = False
    backend.collection.indexes = []
    await backend.store.ensure_collection(vector_dim=3)

    schema = backend.collection_factory.call_args.kwargs["schema"]
    vector_field = next(field for field in schema.fields if field.name == "embedding")
    assert vector_field.params["dim"] == 3
    backend.collection.create_index.assert_called_once()
    backend.collection.load.assert_called_once()
    backend.drop_collection.assert_not_called()


async def test_recreate_collection_explicitly_replaces_schema(milvus_backend):
    backend = milvus_backend
    backend.has_collection.side_effect = [True, False]
    await backend.store.recreate_collection(vector_dim=2)

    backend.drop_collection.assert_called_once_with("test_chunks")
    schema = backend.collection_factory.call_args.kwargs["schema"]
    vector_field = next(field for field in schema.fields if field.name == "embedding")
    assert vector_field.params["dim"] == 2
    backend.collection.load.assert_called_once()


async def test_recreate_rejects_invalid_dimension_before_deleting(milvus_backend):
    backend = milvus_backend
    with pytest.raises(ValueError, match="must be positive"):
        await backend.store.recreate_collection(vector_dim=0)
    backend.drop_collection.assert_not_called()


@pytest.mark.parametrize("hit_format", ["sdk", "dict", "object"])
async def test_search_returns_persistent_chunk_id_and_filters_scores(milvus_backend, hit_format):
    backend = milvus_backend
    entity = {"text": "Twelve days of leave.", "page": 2, "source": "policy.pdf", "doc_id": "doc-1"}
    hits = [
        {"id": "stored-chunk-1", "distance": 0.9, "entity": entity},
        {"id": "stored-chunk-2", "distance": 0.1, "entity": entity},
    ]
    if hit_format == "sdk":
        hits = [Hit(hit, pk_name="id") for hit in hits]
    elif hit_format == "object":
        hits = [
            SimpleNamespace(id=hit["id"], score=hit["distance"], entity=SimpleNamespace(**entity))
            for hit in hits
        ]
    backend.collection.search.return_value = [hits]

    for _ in range(2):
        chunks = await backend.store.search_chunks([0.1, 0.2, 0.3], "doc-1", min_score=0.32)
        assert [chunk.chunk_id for chunk in chunks] == ["stored-chunk-1"]
        assert chunks[0].text == entity["text"]
        assert chunks[0].score == 0.9
    assert backend.collection.search.call_args.kwargs["expr"] == 'doc_id == "doc-1"'


async def test_connection_status_reports_local_state_without_health_claim(milvus_backend):
    backend = milvus_backend
    disconnected = await backend.store.get_connection_status()
    assert disconnected["status"] == "disconnected"
    assert disconnected["connected"] is False

    await backend.store.connect()
    connected = await backend.store.get_connection_status()
    assert connected["status"] == "connected"
    assert connected["connected"] is True
    backend.collection_factory.assert_not_called()
