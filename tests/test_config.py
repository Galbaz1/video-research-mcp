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
