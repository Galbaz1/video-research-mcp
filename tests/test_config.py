"""Tests for configuration parsing and normalization."""

from __future__ import annotations

import pytest

from video_research_mcp.config import ServerConfig


class TestWeaviateUrlNormalization:
    """Verify WEAVIATE_URL normalization from environment variables."""

    def test_cloud_hostname_without_scheme_defaults_to_https(self, monkeypatch):
        monkeypatch.setenv("WEAVIATE_URL", "cluster-id.c0.europe-west3.gcp.weaviate.cloud")
        cfg = ServerConfig.from_env()
        assert cfg.weaviate_url == "https://cluster-id.c0.europe-west3.gcp.weaviate.cloud"
        assert cfg.weaviate_enabled is True

    def test_localhost_without_scheme_defaults_to_http(self, monkeypatch):
        monkeypatch.setenv("WEAVIATE_URL", "localhost:8080")
        cfg = ServerConfig.from_env()
        assert cfg.weaviate_url == "http://localhost:8080"
        assert cfg.weaviate_enabled is True

    def test_public_172_ip_without_scheme_defaults_to_https(self, monkeypatch):
        monkeypatch.setenv("WEAVIATE_URL", "172.67.10.20:8080")
        cfg = ServerConfig.from_env()
        assert cfg.weaviate_url == "https://172.67.10.20:8080"
        assert cfg.weaviate_enabled is True

    def test_private_172_16_ip_without_scheme_defaults_to_http(self, monkeypatch):
        monkeypatch.setenv("WEAVIATE_URL", "172.16.5.10:8080")
        cfg = ServerConfig.from_env()
        assert cfg.weaviate_url == "http://172.16.5.10:8080"
        assert cfg.weaviate_enabled is True

    def test_existing_scheme_is_preserved(self, monkeypatch):
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        cfg = ServerConfig.from_env()
        assert cfg.weaviate_url == "https://test.weaviate.network"
        assert cfg.weaviate_enabled is True

    def test_unresolved_placeholder_is_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("WEAVIATE_URL", "${WEAVIATE_URL}")
        cfg = ServerConfig.from_env()
        assert cfg.weaviate_url == ""
        assert cfg.weaviate_enabled is False

    def test_unresolved_default_placeholder_is_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("WEAVIATE_URL", "${WEAVIATE_URL:-}")
        cfg = ServerConfig.from_env()
        assert cfg.weaviate_url == ""
        assert cfg.weaviate_enabled is False


class TestDocumentConcurrencyConfig:
    """Verify configurable fan-out controls for document pipelines."""

    def test_doc_concurrency_env_overrides_are_applied(self, monkeypatch):
        monkeypatch.setenv("DOC_PREPARE_CONCURRENCY", "6")
        monkeypatch.setenv("DOC_PHASE_CONCURRENCY", "5")
        cfg = ServerConfig.from_env()
        assert cfg.doc_prepare_concurrency == 6
        assert cfg.doc_phase_concurrency == 5

    def test_doc_concurrency_rejects_out_of_range_values(self):
        with pytest.raises(ValueError, match="Document concurrency values"):
            ServerConfig(doc_prepare_concurrency=0)

        with pytest.raises(ValueError, match="Document concurrency values"):
            ServerConfig(doc_phase_concurrency=17)
