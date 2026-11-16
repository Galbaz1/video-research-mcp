"""Current model request contracts using concrete Google GenAI SDK responses."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import types
from pydantic import BaseModel

from video_research_mcp.client import GeminiClient
from video_research_mcp.config import ServerConfig


@pytest.fixture()
def sdk_client(clean_config, monkeypatch):
    """Mock only the external SDK transport, keeping request construction real."""
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_THINKING_LEVEL", raising=False)
    response = types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(role="model", parts=[
            types.Part(text="Thinking summary", thought=True),
            types.Part(text="Answer", thought_signature=b"signature"),
        ]),
    )])
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=response)
    with patch.object(GeminiClient, "get", return_value=client):
        yield client


class TestCurrentModelContract:
    async def test_current_flash_omits_sampling_and_strips_thoughts(self, sdk_client):
        """GIVEN latest Flash WHEN generating THEN request is valid and only answer is returned."""
        text = await GeminiClient.generate("Prompt")
        request = sdk_client.aio.models.generate_content.call_args.kwargs
        config = request["config"].model_dump(exclude_none=True)

        assert request["model"] == "gemini-3.8-flash"
        assert config == {"thinking_config": {"thinking_level": types.ThinkingLevel.MEDIUM}}
        assert text == "Answer"

    async def test_minimal_fails_before_request_for_current_flash(self, sdk_client):
        with pytest.raises(ValueError, match="does not support minimal"):
            await GeminiClient.generate("Prompt", thinking_level="minimal")
        sdk_client.aio.models.generate_content.assert_not_called()

    async def test_explicit_sampling_fails_before_request(self, sdk_client):
        with pytest.raises(ValueError, match="does not support temperature"):
            await GeminiClient.generate("Prompt", temperature=0.7)
        sdk_client.aio.models.generate_content.assert_not_called()

    async def test_compatible_explicit_model_retains_sampling(self, sdk_client):
        await GeminiClient.generate(
            "Prompt", model="gemini-3.5-flash-lite", thinking_level="minimal", temperature=0.7,
        )
        config = sdk_client.aio.models.generate_content.call_args.kwargs["config"]
        assert config.temperature == 0.7
        assert config.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL

    async def test_blocked_candidate_with_no_content_returns_empty_text(self, sdk_client):
        sdk_client.aio.models.generate_content.return_value = types.GenerateContentResponse(
            candidates=[types.Candidate(finish_reason="SAFETY")],
        )
        assert await GeminiClient.generate("Prompt") == ""

    async def test_structured_output_passes_schema_and_validates(self, sdk_client):
        class Output(BaseModel):
            answer: str

        sdk_client.aio.models.generate_content.return_value = types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(role="model", parts=[
                types.Part(text='{"answer": "valid"}'),
            ]))],
        )
        result = await GeminiClient.generate_structured("Prompt", schema=Output)
        config = sdk_client.aio.models.generate_content.call_args.kwargs["config"]
        assert result.answer == "valid"
        assert config.response_json_schema == Output.model_json_schema()
        assert config.response_mime_type == "application/json"

    def test_config_rejects_invalid_model_thinking_combination(self):
        with pytest.raises(ValueError, match="does not support minimal"):
            ServerConfig(default_thinking_level="minimal")


GEMINI_4 = ["gemini-4-carbon", "gemini-4-argon", "gemini-4-hydrogen"]


class TestGemini4Contract:
    @pytest.mark.parametrize("model", GEMINI_4)
    async def test_gemini_4_omits_sampling_and_rejects_minimal(self, sdk_client, model):
        """GIVEN a Gemini 4 model THEN no temperature is sent and minimal fails before SDK."""
        await GeminiClient.generate("Prompt", model=model)
        config = sdk_client.aio.models.generate_content.call_args.kwargs["config"]
        assert config.temperature is None
        with pytest.raises(ValueError, match="does not support temperature"):
            await GeminiClient.generate("Prompt", model=model, temperature=0.7)
        with pytest.raises(ValueError, match="does not support minimal"):
            await GeminiClient.generate("Prompt", model=model, thinking_level="minimal")
        assert sdk_client.aio.models.generate_content.await_count == 1

    @pytest.mark.parametrize("model", GEMINI_4)
    def test_gemini_4_config_rejects_minimal(self, model):
        with pytest.raises(ValueError, match="does not support minimal"):
            ServerConfig(default_model=model, default_thinking_level="minimal")

    def test_best_preset_uses_carbon(self):
        from video_research_mcp.config import MODEL_PRESETS, supports_explicit_cache

        assert MODEL_PRESETS["best"]["default_model"] == "gemini-4-carbon"
        assert "Carbon" in MODEL_PRESETS["best"]["label"]
        assert not any(supports_explicit_cache(model) for model in GEMINI_4)
        assert supports_explicit_cache("gemini-3.8-flash")


class TestStreaming:
    async def test_stream_joins_visible_chunks_with_a_long_deadline(self, sdk_client):
        """GIVEN split JSON chunks WHEN streaming THEN text joins exactly and thoughts drop."""
        def chunk(*parts):
            return types.GenerateContentResponse(candidates=[types.Candidate(
                content=types.Content(role="model", parts=list(parts)))])

        async def stream(**kwargs):
            async def chunks():
                yield chunk(types.Part(text="plan", thought=True))
                yield chunk(types.Part(text='{"answer": "va'))
                yield chunk(types.Part(text='lid"}'))
            return chunks()

        sdk_client.aio.models.generate_content_stream = AsyncMock(side_effect=stream)
        text = await GeminiClient.generate("Prompt", stream=True)
        config = sdk_client.aio.models.generate_content_stream.call_args.kwargs["config"]
        assert text == '{"answer": "valid"}'
        assert config.http_options.timeout == 600_000
        sdk_client.aio.models.generate_content.assert_not_called()

    def test_shared_client_uses_v1beta(self, monkeypatch):
        """GIVEN SDK 3 (default v1) THEN the shared client keeps v1beta for agentic video."""
        from google import genai

        captured = {}
        monkeypatch.setattr(GeminiClient, "_clients", {})
        monkeypatch.setattr(genai, "Client", lambda **kwargs: captured.update(kwargs) or MagicMock())
        GeminiClient.get("fixture-key")
        assert captured["http_options"].api_version == "v1beta"
