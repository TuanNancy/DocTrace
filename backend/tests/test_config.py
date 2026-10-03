"""Resolved settings are the sole source of runtime parameters."""
from unittest.mock import MagicMock

import pytest

from app.core.config import AppConfig
from app.storage.factory import create_vector_store
from app.providers.factory import create_chat_provider


def test_explicit_config_does_not_read_environment(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_TOP_K", "99")
    assert AppConfig(retrieval_top_k=12).retrieval_top_k == 12
    assert AppConfig.from_env().retrieval_top_k == 99


def test_local_cloud_and_index_override():
    local = create_vector_store(AppConfig.from_env({}))
    assert (local.host, local.port, local.index_type) == ("localhost", 19530, "IVF_FLAT")
    cloud = create_vector_store(AppConfig.from_env({"MILVUS_URI": "https://cluster.test", "MILVUS_TOKEN": "token"}))
    assert (cloud.uri, cloud.token, cloud.index_type) == ("https://cluster.test", "token", "AUTOINDEX")
    config = AppConfig.from_env({"MILVUS_URI": "https://cluster.test", "MILVUS_INDEX_TYPE": "HNSW"})
    assert create_vector_store(config).index_type == "HNSW"


@pytest.mark.parametrize("key,value", [
    ("RETRIEVAL_TOP_K", "0"), ("CONTEXT_MAX_CHARS", "-1"), ("RAG_MAX_TOKENS", "0"),
    ("CHUNK_OVERLAP", "1000"), ("EMBEDDING_BATCH_SIZE", "0"),
    ("UPSTREAM_TIMEOUT_SECONDS", "nan"), ("UPLOAD_MAX_CONCURRENT", "0"),
    ("MAX_CHUNKS_PER_DOCUMENT", "-1"), ("MILVUS_PORT", "70000"),
    ("DOCUMENT_INDEX_TIMEOUT_SECONDS", "0"), ("DOCUMENT_DELETE_TIMEOUT_SECONDS", "-1"),
    ("REDIS_URL", "https://wrong.test"),
])
def test_invalid_values_name_the_setting(key, value):
    with pytest.raises(ValueError, match=key):
        AppConfig.from_env({key: value})


def test_invalid_numeric_value_is_not_exposed():
    with pytest.raises(ValueError) as error:
        AppConfig.from_env({"RETRIEVAL_TOP_K": "private-value"})
    assert "RETRIEVAL_TOP_K" in str(error.value)
    assert "private-value" not in str(error.value)


def test_s3_can_be_disabled_but_partial_credentials_are_rejected():
    AppConfig.from_env({"SUPABASE_STORAGE_BUCKET": "pdfs"})
    with pytest.raises(ValueError, match="SUPABASE_S3_SECRET_ACCESS_KEY"):
        AppConfig.from_env({"SUPABASE_S3_ACCESS_KEY_ID": "private-id"})


def test_required_models_do_not_silently_fall_back():
    config = AppConfig(openrouter_api_key="test-key")
    with pytest.raises(ValueError, match="RAG_MODEL"):
        create_chat_provider(config)
    with pytest.raises(ValueError, match="EMBEDDING_MODEL"):
        config.require_openrouter(embeddings=True)


async def test_injected_config_reaches_real_milvus_search(monkeypatch):
    from app.ai import rag_pipeline
    from app.storage import milvus_vector_store as milvus
    from app.providers import embeddings

    config = AppConfig.from_env({
        "RETRIEVAL_TOP_K": "12", "MIN_RELEVANCE_SCORE": "0.2", "RAG_MODEL": "custom-chat",
        "EMBEDDING_MODEL": "custom-embed", "OPENROUTER_API_KEY": "test-key",
        "OPENROUTER_BASE_URL": "https://custom.test/v1", "UPSTREAM_TIMEOUT_SECONDS": "17",
        "EMBEDDING_BATCH_SIZE": "3", "MILVUS_COLLECTION": "custom_chunks",
    })
    collection = MagicMock()
    collection.search.return_value = [[]]
    monkeypatch.setattr(milvus, "connections", MagicMock())
    factory = MagicMock(return_value=collection)
    monkeypatch.setattr(milvus, "Collection", factory)
    embedder = MagicMock()
    embedder.embed_documents.return_value = [[1, 2, 3]]
    make_embedder = MagicMock(return_value=embedder)
    monkeypatch.setattr(embeddings, "_cached_embedder", make_embedder)
    pipeline = rag_pipeline.RAGPipeline(config=config)
    await pipeline.initialize()
    try:
        assert pipeline.chat_provider.model == "custom-chat"
        assert pipeline.chat_provider.base_url == "https://custom.test/v1"
        assert pipeline.chat_provider.timeout == 17
        assert await pipeline.retrieve_chunks("How much leave?", "doc", user_id="owner") == []
        assert collection.search.call_args.kwargs["limit"] == 12
        assert collection.search.call_args.kwargs["expr"] == 'user_id == "owner" and doc_id == "doc"'
        assert factory.call_args.args[0] == "custom_chunks"
        make_embedder.assert_called_once_with("custom-embed", "test-key", "https://custom.test/v1", 17, 3)
    finally:
        await pipeline.shutdown()


def test_diagnostic_script_uses_config_unless_explicitly_overridden():
    from scripts.test_retrieval import parse_args
    config = AppConfig(retrieval_top_k=12, min_relevance_score=0.21)
    args = parse_args(["owner", "doc", "question"], config=config)
    assert (args.top_k, args.min_score) == (12, 0.21)
    args = parse_args(["owner", "doc", "question", "--top-k", "3", "--min-score", "0.1"], config=config)
    assert (args.top_k, args.min_score) == (3, 0.1)


def test_file_precedence_and_config_cache(monkeypatch, tmp_path):
    from pathlib import Path
    from app.core import config as module
    # config.py resolves parents[3] as the repository root.
    monkeypatch.setattr(module, "__file__", str(tmp_path / "backend/app/core/config.py"))
    (tmp_path / "backend").mkdir()
    (tmp_path / ".env").write_text("RETRIEVAL_TOP_K=9\nCHUNK_SIZE=777\n")
    (tmp_path / "backend/.env").write_text("RETRIEVAL_TOP_K=12\n")
    for key in ("CHUNK_SIZE", "MILVUS_URI", "MILVUS_TOKEN", "SUPABASE_S3_ENDPOINT",
                "SUPABASE_S3_ACCESS_KEY_ID", "SUPABASE_S3_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("RETRIEVAL_TOP_K", "5")
    monkeypatch.setattr(module, "_config", None)
    config = module.get_config()
    assert (config.retrieval_top_k, config.chunk_size) == (12, 777)
    (tmp_path / "backend/.env").write_text("RETRIEVAL_TOP_K=13\n")
    assert module.get_config() is config
    assert config.retrieval_top_k == 12


def test_embedder_cache_includes_endpoint_and_batch_settings(monkeypatch):
    from dataclasses import replace
    from app.providers import embeddings
    constructor = MagicMock(side_effect=lambda **kwargs: object())
    monkeypatch.setattr(embeddings, "OpenRouterEmbedder", constructor)
    embeddings._cached_embedder.cache_clear()
    config = AppConfig(embedding_model="test-embedding", openrouter_api_key="test-key")
    try:
        first = embeddings.get_embedder(config=config)
        assert embeddings.get_embedder(config=replace(config)) is first
        assert embeddings.get_embedder(config=replace(config, openrouter_base_url="https://other.test/v1")) is not first
        assert embeddings.get_embedder(config=replace(config, embedding_batch_size=3)) is not first
        assert constructor.call_count == 3
    finally:
        embeddings._cached_embedder.cache_clear()
