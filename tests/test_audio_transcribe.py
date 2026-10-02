"""Verify public transcription errors, cancellation and optional configuration."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from video_research_mcp.config import ServerConfig
from video_research_mcp.models.transcript import TranscriptRequest
from video_research_mcp.tools import audio_transcribe as tool


@pytest.fixture
def transcript_request(tmp_path):
    """Return a typed boundary request without accessing source media."""
    return TranscriptRequest(
        file_path=str(tmp_path / "source.wav"),
        expected_source_sha256="a" * 64,
        output_directory=str(tmp_path / "output"),
    )


async def test_public_error_is_structured(monkeypatch, transcript_request):
    """GIVEN a source refusal WHEN called publicly THEN no exception escapes."""
    monkeypatch.setattr(tool, "transcribe", AsyncMock(side_effect=ValueError("source changed")))
    result = await tool.audio_transcribe(transcript_request)
    assert result["error"] == "source changed"
    assert result["retryable"] is False


async def test_public_cancellation_propagates(monkeypatch, transcript_request):
    """GIVEN caller cancellation WHEN dispatched THEN task ownership can terminate."""
    monkeypatch.setattr(tool, "transcribe", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await tool.audio_transcribe(transcript_request)


def test_optional_service_is_disabled(monkeypatch):
    """GIVEN no service configuration THEN core startup needs no ASR service."""
    monkeypatch.delenv("ASR_SERVICE_JSON", raising=False)
    assert ServerConfig.from_env().asr_service is None


def test_service_configuration_is_typed_and_unqualified(monkeypatch):
    """GIVEN an explicit local origin THEN its model remains unattested by default."""
    monkeypatch.setenv("ASR_SERVICE_JSON", json.dumps({
        "base_url": "http://127.0.0.1:9000", "local": True,
    }))
    service = ServerConfig.from_env().asr_service
    assert service.local is True
    assert service.runtime_qualified is False


def test_local_configuration_rejects_remote_origin(monkeypatch):
    """GIVEN a local-only profile with a remote origin THEN startup refuses it."""
    monkeypatch.setenv("ASR_SERVICE_JSON", json.dumps({
        "base_url": "https://example.invalid", "local": True,
    }))
    with pytest.raises(ValueError, match="literal loopback"):
        ServerConfig.from_env()
