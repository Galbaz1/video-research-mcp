"""Tests for config module."""

from __future__ import annotations

import pytest

from video_explainer_mcp.config import ServerConfig, get_config, update_config
import video_explainer_mcp.config as cfg_mod

pytestmark = pytest.mark.unit



@pytest.fixture(autouse=True)
def _clean_config():
    """Reset the config singleton between tests."""
    cfg_mod._config = None
    yield
    cfg_mod._config = None


class TestServerConfig:
    """Tests for ServerConfig model."""

    def test_defaults(self):
        """All fields have sensible defaults."""
        cfg = ServerConfig()
        assert cfg.explainer_path == ""
        assert cfg.tts_provider == "mock"
        assert cfg.timeout == 600
        assert cfg.render_timeout == 1800
        assert cfg.explainer_enabled is False
        assert cfg.dashscope_image_base_url == ""

    def test_from_env(self, monkeypatch):
        """from_env reads env vars correctly."""
        monkeypatch.setenv("EXPLAINER_PATH", "/opt/explainer")
        monkeypatch.setenv("EXPLAINER_TTS_PROVIDER", "elevenlabs")
        monkeypatch.setenv("EXPLAINER_TIMEOUT", "300")
        monkeypatch.setenv("EXPLAINER_DASHSCOPE_IMAGE_BASE_URL", "https://workspace.example/api/v1")
        cfg = ServerConfig.from_env()
        assert cfg.explainer_path == "/opt/explainer"
        assert cfg.tts_provider == "elevenlabs"
        assert cfg.timeout == 300
        assert cfg.explainer_enabled is True
        assert cfg.dashscope_image_base_url == "https://workspace.example/api/v1"

    def test_from_env_non_numeric_timeout_uses_default(self, monkeypatch):
        """Non-numeric EXPLAINER_TIMEOUT falls back to default instead of crashing."""
        monkeypatch.setenv("EXPLAINER_TIMEOUT", "600s")
        monkeypatch.setenv("EXPLAINER_RENDER_TIMEOUT", "not-a-number")
        cfg = ServerConfig.from_env()
        assert cfg.timeout == 600
        assert cfg.render_timeout == 1800

    @pytest.mark.parametrize("provider", ["invalid", "openai", "gemini"])
    def test_invalid_tts_provider(self, provider):
        """Reject providers unsupported by the upstream voiceover CLI."""
        with pytest.raises(ValueError, match="Invalid TTS provider"):
            ServerConfig(tts_provider=provider)

    @pytest.mark.parametrize("provider", ["mock", "elevenlabs", "edge"])
    def test_supported_tts_provider(self, provider):
        """Keep supported provider values normalized for CLI forwarding."""
        assert ServerConfig(tts_provider=f" {provider.upper()} ").tts_provider == provider

    @pytest.mark.parametrize("provider", ["openai", "gemini"])
    def test_unsupported_tts_provider_from_env(self, monkeypatch, provider):
        """Reject unsupported environment configuration before spawning the CLI."""
        monkeypatch.setenv("EXPLAINER_TTS_PROVIDER", provider)
        with pytest.raises(ValueError, match="Invalid TTS provider"):
            ServerConfig.from_env()

    def test_invalid_timeout(self):
        """Non-positive timeout raises ValueError."""
        with pytest.raises(ValueError, match="must be >= 1"):
            ServerConfig(timeout=0)

    def test_resolved_projects_path_with_projects_path(self):
        """Explicit EXPLAINER_PROJECTS_PATH takes precedence."""
        cfg = ServerConfig(explainer_path="/opt/explainer", projects_path="/custom/projects")
        assert str(cfg.resolved_projects_path) == "/custom/projects"

    def test_resolved_projects_path_default(self):
        """Default projects path is explainer_path/projects."""
        cfg = ServerConfig(explainer_path="/opt/explainer")
        assert str(cfg.resolved_projects_path) == "/opt/explainer/projects"

    def test_explainer_enabled_when_path_set(self):
        """explainer_enabled is True when explainer_path is non-empty."""
        cfg = ServerConfig(explainer_path="/some/path")
        assert cfg.explainer_enabled is True


class TestGetConfig:
    """Tests for the config singleton."""

    def test_get_config_creates_singleton(self, monkeypatch, tmp_path):
        """get_config creates config on first call."""
        monkeypatch.setattr("video_explainer_mcp.dotenv.DEFAULT_ENV_PATH", tmp_path / "nope.env")
        cfg = get_config()
        assert isinstance(cfg, ServerConfig)
        assert get_config() is cfg  # Same instance

    def test_update_config(self, monkeypatch, tmp_path):
        """update_config patches live config."""
        monkeypatch.setattr("video_explainer_mcp.dotenv.DEFAULT_ENV_PATH", tmp_path / "nope.env")
        updated = update_config(tts_provider="edge")
        assert updated.tts_provider == "edge"
