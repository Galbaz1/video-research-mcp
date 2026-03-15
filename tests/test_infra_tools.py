"""Tests for infrastructure tools."""

from __future__ import annotations

import pytest

import video_research_mcp.config as cfg_mod
import video_research_mcp.tools.infra as infra_mod
from tests.conftest import unwrap_tool

infra_cache = unwrap_tool(infra_mod.infra_cache)
infra_configure = unwrap_tool(infra_mod.infra_configure)


@pytest.fixture(autouse=True)
def _clean_config(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("INFRA_MUTATIONS_ENABLED", "true")
    cfg_mod._config = None
    yield
    cfg_mod._config = None


class TestInfraTools:
    @pytest.mark.asyncio
    async def test_infra_configure_updates_runtime_config(self):
        out = await infra_configure(model="gemini-test", thinking_level="low", temperature=0.7)
        cfg = out["current_config"]
        assert cfg["default_model"] == "gemini-test"
        assert cfg["default_thinking_level"] == "low"
        assert cfg["default_temperature"] == 0.7
        assert "gemini_api_key" not in cfg

    @pytest.mark.asyncio
    async def test_infra_configure_redacts_all_secret_fields(self, monkeypatch):
        monkeypatch.setenv("YOUTUBE_API_KEY", "youtube-secret")
        monkeypatch.setenv("WEAVIATE_API_KEY", "weaviate-secret")
        monkeypatch.setenv("INFRA_ADMIN_TOKEN", "infra-secret")
        cfg_mod._config = None

        out = await infra_configure()
        cfg = out["current_config"]

        assert "gemini_api_key" not in cfg
        assert "youtube_api_key" not in cfg
        assert "weaviate_api_key" not in cfg
        assert "infra_admin_token" not in cfg

    @pytest.mark.asyncio
    async def test_infra_configure_invalid_thinking_level_returns_error(self):
        out = await infra_configure(thinking_level="ultra")
        assert out["category"] == "API_INVALID_ARGUMENT"
        assert out["retryable"] is False

    @pytest.mark.asyncio
    async def test_preset_sets_both_models(self):
        out = await infra_configure(preset="stable")
        cfg = out["current_config"]
        assert cfg["default_model"] == "gemini-3-pro-preview"
        assert cfg["flash_model"] == "gemini-3-flash-preview"
        assert out["active_preset"] == "stable"

    @pytest.mark.asyncio
    async def test_preset_with_model_override(self):
        out = await infra_configure(preset="stable", model="gemini-3-pro-exp-override")
        cfg = out["current_config"]
        assert cfg["default_model"] == "gemini-3-pro-exp-override"
        assert cfg["flash_model"] == "gemini-3-flash-preview"
        assert out["active_preset"] is None  # no exact preset match

    @pytest.mark.asyncio
    async def test_invalid_preset_returns_error(self):
        out = await infra_configure(preset="turbo")
        assert out["category"] == "UNKNOWN"
        assert "Unknown preset" in out["error"]

    @pytest.mark.asyncio
    async def test_response_includes_presets(self):
        out = await infra_configure()
        assert "available_presets" in out
        assert set(out["available_presets"]) == {"best", "stable", "budget"}
        assert out["active_preset"] == "best"  # default models match "best"

    @pytest.mark.asyncio
    async def test_infra_configure_blocks_mutation_when_disabled(self, monkeypatch):
        monkeypatch.setenv("INFRA_MUTATIONS_ENABLED", "false")
        cfg_mod._config = None

        out = await infra_configure(model="gemini-test")

        assert out["category"] == "PERMISSION_DENIED"
        assert out["retryable"] is False

    @pytest.mark.asyncio
    async def test_infra_configure_allows_read_only_when_disabled(self, monkeypatch):
        monkeypatch.setenv("INFRA_MUTATIONS_ENABLED", "false")
        cfg_mod._config = None

        out = await infra_configure()

        assert "current_config" in out
        assert out["active_preset"] == "best"

    @pytest.mark.asyncio
    async def test_infra_configure_requires_token_when_configured(self, monkeypatch):
        monkeypatch.setenv("INFRA_ADMIN_TOKEN", "top-secret")
        cfg_mod._config = None

        denied = await infra_configure(model="gemini-test")
        assert denied["category"] == "PERMISSION_DENIED"

        allowed = await infra_configure(model="gemini-test", auth_token="top-secret")
        assert allowed["current_config"]["default_model"] == "gemini-test"

    @pytest.mark.asyncio
    async def test_infra_cache_unknown_action(self):
        out = await infra_cache(action="wat")
        assert "Unknown action" in out["error"]

    @pytest.mark.asyncio
    async def test_infra_cache_clear_blocked_without_mutation_permission(self, monkeypatch):
        monkeypatch.setenv("INFRA_MUTATIONS_ENABLED", "false")
        cfg_mod._config = None

        out = await infra_cache(action="clear", content_id="abc")
        assert out["category"] == "PERMISSION_DENIED"

    @pytest.mark.asyncio
    async def test_infra_cache_clear_requires_token_when_configured(self, monkeypatch):
        monkeypatch.setenv("INFRA_ADMIN_TOKEN", "cache-token")
        cfg_mod._config = None
        monkeypatch.setattr("video_research_mcp.tools.infra.cache_mod.clear", lambda _cid: 1)

        denied = await infra_cache(action="clear", content_id="abc")
        assert denied["category"] == "PERMISSION_DENIED"

        allowed = await infra_cache(action="clear", content_id="abc", auth_token="cache-token")
        assert allowed["removed"] == 1

    @pytest.mark.asyncio
    async def test_infra_cache_context_action(self):
        """GIVEN cache subsystem state WHEN action=context THEN returns diagnostic dict."""
        import video_research_mcp.context_cache as cc_mod

        cc_mod._loaded = True
        cc_mod._registry[("vid1", "model-a")] = "cachedContents/aaa"
        cc_mod._suppressed.add(("short", "model-a"))
        cc_mod._last_failure[("fail", "model-a")] = "api_error:TimeoutError"

        try:
            out = await infra_cache(action="context")

            assert "registry" in out
            assert "suppressed" in out
            assert "pending" in out
            assert "recent_failures" in out
            assert out["registry"] == {"vid1/model-a": "cachedContents/aaa"}
            assert "short/model-a" in out["suppressed"]
            assert out["recent_failures"]["fail/model-a"] == "api_error:TimeoutError"
        finally:
            cc_mod._registry.clear()
            cc_mod._suppressed.clear()
            cc_mod._last_failure.clear()
