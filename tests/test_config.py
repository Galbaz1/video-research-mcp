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


class TestVectorizerConfig:
    """Verify WEAVIATE_VECTORIZER and WEAVIATE_AUTO_MIGRATE config."""

    def test_default_openai(self, monkeypatch):
        """No env vars → openai vectorizer."""
        monkeypatch.delenv("WEAVIATE_VECTORIZER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg = ServerConfig.from_env()
        assert cfg.weaviate_vectorizer == "openai"

    def test_explicit_weaviate_override(self, monkeypatch):
        """WEAVIATE_VECTORIZER=weaviate overrides auto-detection."""
        monkeypatch.setenv("WEAVIATE_VECTORIZER", "weaviate")
        cfg = ServerConfig.from_env()
        assert cfg.weaviate_vectorizer == "weaviate"

    def test_cloud_without_openai_autodetects_weaviate(self, monkeypatch):
        """https URL + no OPENAI_API_KEY → weaviate vectorizer."""
        monkeypatch.delenv("WEAVIATE_VECTORIZER", raising=False)
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.cloud")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg = ServerConfig.from_env()
        assert cfg.weaviate_vectorizer == "weaviate"

    def test_cloud_with_openai_stays_openai(self, monkeypatch):
        """https URL + OPENAI_API_KEY → openai vectorizer."""
        monkeypatch.delenv("WEAVIATE_VECTORIZER", raising=False)
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.cloud")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg = ServerConfig.from_env()
        assert cfg.weaviate_vectorizer == "openai"

    def test_local_always_openai(self, monkeypatch):
        """http localhost URL → openai vectorizer."""
        monkeypatch.delenv("WEAVIATE_VECTORIZER", raising=False)
        monkeypatch.setenv("WEAVIATE_URL", "http://localhost:8080")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg = ServerConfig.from_env()
        assert cfg.weaviate_vectorizer == "openai"

    def test_invalid_vectorizer_raises(self, monkeypatch):
        """WEAVIATE_VECTORIZER=cohere → ValueError."""
        monkeypatch.setenv("WEAVIATE_VECTORIZER", "cohere")
        with pytest.raises(Exception, match="WEAVIATE_VECTORIZER must be"):
            ServerConfig.from_env()

    def test_auto_migrate_default_false(self, monkeypatch):
        """No env var → auto_migrate is False."""
        monkeypatch.delenv("WEAVIATE_AUTO_MIGRATE", raising=False)
        cfg = ServerConfig.from_env()
        assert cfg.weaviate_auto_migrate is False

    def test_auto_migrate_explicit_true(self, monkeypatch):
        """WEAVIATE_AUTO_MIGRATE=true → True."""
        monkeypatch.setenv("WEAVIATE_AUTO_MIGRATE", "true")
        cfg = ServerConfig.from_env()
        assert cfg.weaviate_auto_migrate is True


class TestDeepResearchAgentValidator:
    """Verify DEEP_RESEARCH_AGENT validation at config load."""

    def test_empty_agent_string_raises(self, monkeypatch):
        monkeypatch.setenv("DEEP_RESEARCH_AGENT", "  ")
        with pytest.raises(Exception, match="DEEP_RESEARCH_AGENT must not be empty"):
            ServerConfig.from_env()

    def test_valid_agent_string_passes(self, monkeypatch):
        monkeypatch.setenv("DEEP_RESEARCH_AGENT", "custom-agent-v3")
        cfg = ServerConfig.from_env()
        assert cfg.deep_research_agent == "custom-agent-v3"
