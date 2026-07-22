"""Tests for Gemini request configuration."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import video_research_mcp.config as config_module
from video_research_mcp.client import GeminiClient


@pytest.fixture(autouse=True)
def _reset_config():
    config_module._config = None
    yield
    config_module._config = None


async def test_gemini_36_omits_deprecated_sampling_parameters(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.6-flash")
    mock_generate = AsyncMock(
        return_value=SimpleNamespace(candidates=[], text="response")
    )
    client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=mock_generate))
    )

    with patch.object(GeminiClient, "get", return_value=client):
        result = await GeminiClient.generate("prompt", temperature=0.2)

    assert result == "response"
    request_config = mock_generate.call_args.kwargs["config"]
    assert request_config.temperature is None


async def test_older_models_keep_temperature_support(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-pro-preview")
    mock_generate = AsyncMock(
        return_value=SimpleNamespace(candidates=[], text="response")
    )
    client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=mock_generate))
    )

    with patch.object(GeminiClient, "get", return_value=client):
        await GeminiClient.generate("prompt", temperature=0.2)

    request_config = mock_generate.call_args.kwargs["config"]
    assert request_config.temperature == 0.2
