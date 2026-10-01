"""Local/cloud configuration resolves into the same vector-store adapter."""
import pytest

from app.core.config import AppConfig
from app.storage.factory import VectorStoreFactory


def test_cloud_defaults_to_autoindex_and_passes_credentials(monkeypatch):
    monkeypatch.setenv("MILVUS_URI", "https://cluster.example.com")
    monkeypatch.setenv("MILVUS_TOKEN", "test-token")
    monkeypatch.delenv("MILVUS_INDEX_TYPE", raising=False)
    config = AppConfig()
    values = VectorStoreFactory._get_config_for_backend("milvus", config)
    assert values["uri"] == "https://cluster.example.com"
    assert values["token"] == "test-token"
    assert values["index_type"] == "AUTOINDEX"


def test_local_keeps_ivf_index_and_host_port(monkeypatch):
    for key in ("MILVUS_URI", "MILVUS_TOKEN", "MILVUS_INDEX_TYPE", "MILVUS_HOST", "MILVUS_PORT"):
        monkeypatch.delenv(key, raising=False)
    config = AppConfig()
    assert config.milvus_index_type == "IVF_FLAT"
    assert (config.milvus_host, config.milvus_port) == ("localhost", 19530)


@pytest.mark.parametrize("key", ["UPLOAD_MAX_CONCURRENT", "MAX_CHUNKS_PER_DOCUMENT", "EMBEDDING_BATCH_SIZE", "UPSTREAM_TIMEOUT_SECONDS"])
def test_resource_limits_must_be_positive(monkeypatch, key):
    monkeypatch.setenv(key, "0")
    with pytest.raises(ValueError, match="positive"):
        AppConfig()
