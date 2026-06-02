"""Tests for the shared video analysis pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from google.genai import types

import pytest

from video_research_mcp.models.video import VideoResult
from video_research_mcp.tools.video_core import (
    _ANALYSIS_PREAMBLE,
    _enrich_prompt,
    analyze_video,
)


def _make_content(text: str = "test") -> types.Content:
    return types.Content(parts=[types.Part(text=text)])


def _make_video_content(text: str = "test") -> types.Content:
    """Content with a file_data part + text part (mimics real video content)."""
    return types.Content(parts=[
        types.Part(file_data=types.FileData(file_uri="https://example.com/vid")),
        types.Part(text=text),
    ])


class TestAnalyzeVideo:
    @pytest.mark.asyncio
    async def test_default_schema(self, mock_gemini_client):
        """Uses generate_structured with VideoResult when no custom schema."""
        mock_gemini_client["generate_structured"].return_value = VideoResult(
            title="Test",
            summary="Summary",
        )

        result = await analyze_video(
            _make_content(),
            instruction="summarize",
            content_id="vid123",
            source_label="https://youtube.com/watch?v=vid123",
            use_cache=False,
        )

        assert result["title"] == "Test"
        assert result["source"] == "https://youtube.com/watch?v=vid123"
        mock_gemini_client["generate_structured"].assert_called_once()

    @pytest.mark.asyncio
    async def test_custom_schema(self, mock_gemini_client):
        """Uses generate with custom schema when output_schema provided."""
        mock_gemini_client["generate"].return_value = '{"items": [1, 2]}'
        schema = {"type": "object", "properties": {"items": {"type": "array"}}}

        result = await analyze_video(
            _make_content(),
            instruction="extract items",
            content_id="vid456",
            source_label="/path/to/file.mp4",
            output_schema=schema,
            use_cache=False,
        )

        assert result["items"] == [1, 2]
        assert result["source"] == "/path/to/file.mp4"
        mock_gemini_client["generate"].assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_hit(self, mock_gemini_client, tmp_path, monkeypatch):
        """Returns cached result without calling Gemini."""
        from video_research_mcp import cache

        monkeypatch.setattr(cache, "_cache_dir", lambda: tmp_path)
        cache.save("cached_id", "video_analyze", "test-model", {"title": "Cached"}, instruction="test")

        # Patch get_config to return matching model
        from video_research_mcp.config import ServerConfig
        from unittest.mock import patch

        cfg = ServerConfig(gemini_api_key="test-key-not-real", default_model="test-model")
        with patch("video_research_mcp.tools.video_core.get_config", return_value=cfg):
            result = await analyze_video(
                _make_content(),
                instruction="test",
                content_id="cached_id",
                source_label="some-url",
                use_cache=True,
            )

        assert result["title"] == "Cached"
        assert result["cached"] is True
        mock_gemini_client["generate_structured"].assert_not_called()
        mock_gemini_client["generate"].assert_not_called()

    @pytest.mark.asyncio
    async def test_passes_local_media_fields_to_store(self, mock_gemini_client):
        """When media paths are provided, analyze_video forwards them to Weaviate store."""
        mock_gemini_client["generate_structured"].return_value = VideoResult(title="Test")

        with patch(
            "video_research_mcp.weaviate_store.store_video_analysis",
            new_callable=AsyncMock,
        ) as mock_store:
            await analyze_video(
                _make_content(),
                instruction="summarize",
                content_id="vid123",
                source_label="https://youtube.com/watch?v=vid123",
                use_cache=False,
                local_filepath="/tmp/video.mp4",
                screenshot_dir="/tmp/screens/vid123",
            )

        assert mock_store.await_count == 1
        call_kwargs = mock_store.call_args.kwargs
        assert call_kwargs["local_filepath"] == "/tmp/video.mp4"
        assert call_kwargs["screenshot_dir"] == "/tmp/screens/vid123"

    @pytest.mark.asyncio
    async def test_cache_discriminator_prevents_window_collision(
        self, mock_gemini_client, tmp_path, monkeypatch
    ):
        """Same content_id+instruction but different windows must not share a cache entry."""
        from video_research_mcp import cache
        from video_research_mcp.config import ServerConfig

        monkeypatch.setattr(cache, "_cache_dir", lambda: tmp_path)
        # Seed a cache entry for window A only.
        cache.save(
            "disc_id", "video_analyze", "test-model",
            {"title": "Window A"},
            instruction="test|win:0s-27m@1.0",
        )
        mock_gemini_client["generate_structured"].return_value = VideoResult(title="Window B")
        cfg = ServerConfig(gemini_api_key="test-key-not-real", default_model="test-model")

        with patch("video_research_mcp.tools.video_core.get_config", return_value=cfg):
            hit = await analyze_video(
                _make_video_content(), instruction="test", content_id="disc_id",
                source_label="src", use_cache=True,
                cache_discriminator="|win:0s-27m@1.0",
            )
            miss = await analyze_video(
                _make_video_content(), instruction="test", content_id="disc_id",
                source_label="src", use_cache=True,
                cache_discriminator="|win:27m-54m@1.0",
            )

        assert hit["title"] == "Window A"
        assert hit["cached"] is True
        # Different window → cache miss → fresh Gemini call returns Window B.
        assert miss["title"] == "Window B"
        mock_gemini_client["generate_structured"].assert_called_once()


class TestEnrichPrompt:
    def test_replaces_text_part(self):
        """Text part is replaced with enriched prompt."""
        content = _make_video_content("original prompt")
        enriched = _enrich_prompt(content, "new prompt")

        assert enriched.parts[1].text == "new prompt"
        # Non-text parts are preserved
        assert enriched.parts[0].file_data is not None

    def test_preserves_non_text_parts(self):
        """File data and other non-text parts are unchanged."""
        content = _make_video_content("original")
        enriched = _enrich_prompt(content, "enriched")

        assert enriched.parts[0].file_data.file_uri == "https://example.com/vid"
        assert len(enriched.parts) == 2


class TestPromptEnrichment:
    @pytest.mark.asyncio
    async def test_default_schema_enriches_prompt(self, mock_gemini_client):
        """Default schema path prepends analysis preamble to instruction."""
        mock_gemini_client["generate_structured"].return_value = VideoResult(
            title="Test",
        )

        await analyze_video(
            _make_video_content("summarize this"),
            instruction="summarize this",
            content_id="vid789",
            source_label="https://youtube.com/watch?v=vid789",
            use_cache=False,
        )

        # Verify the enriched prompt was passed to generate_structured
        call_args = mock_gemini_client["generate_structured"].call_args
        contents = call_args.args[0]
        assert _ANALYSIS_PREAMBLE in contents.parts[1].text
        assert "summarize this" in contents.parts[1].text

    @pytest.mark.asyncio
    async def test_custom_schema_skips_enrichment(self, mock_gemini_client):
        """Custom schema path does NOT enrich the prompt."""
        mock_gemini_client["generate"].return_value = '{"items": []}'

        await analyze_video(
            _make_video_content("extract items"),
            instruction="extract items",
            content_id="vid000",
            source_label="/path/to/file.mp4",
            output_schema={"type": "object", "properties": {"items": {"type": "array"}}},
            use_cache=False,
        )

        call_args = mock_gemini_client["generate"].call_args
        contents = call_args.args[0]
        # Original prompt should be unchanged
        assert contents.parts[1].text == "extract items"
        assert _ANALYSIS_PREAMBLE not in contents.parts[1].text


class TestMetadataContext:
    @pytest.mark.asyncio
    async def test_metadata_context_included_in_enriched_prompt(self, mock_gemini_client):
        """Metadata context appears in the enriched prompt sent to Gemini."""
        mock_gemini_client["generate_structured"].return_value = VideoResult(title="Test")

        await analyze_video(
            _make_video_content("summarize"),
            instruction="summarize",
            content_id="vid_meta",
            source_label="https://youtube.com/watch?v=vid_meta",
            use_cache=False,
            metadata_context='Video context: "CLI Tutorial" by TechChannel (Education, 12:34)',
        )

        call_args = mock_gemini_client["generate_structured"].call_args
        contents = call_args.args[0]
        prompt_text = contents.parts[1].text
        assert _ANALYSIS_PREAMBLE in prompt_text
        assert "CLI Tutorial" in prompt_text
        assert "TechChannel" in prompt_text
        assert "User instruction: summarize" in prompt_text

    @pytest.mark.asyncio
    async def test_no_metadata_context_uses_original_enrichment(self, mock_gemini_client):
        """None metadata_context → original enrichment without metadata section."""
        mock_gemini_client["generate_structured"].return_value = VideoResult(title="Test")

        await analyze_video(
            _make_video_content("summarize"),
            instruction="summarize",
            content_id="vid_no_meta",
            source_label="https://youtube.com/watch?v=vid_no_meta",
            use_cache=False,
            metadata_context=None,
        )

        call_args = mock_gemini_client["generate_structured"].call_args
        contents = call_args.args[0]
        prompt_text = contents.parts[1].text
        expected = f"{_ANALYSIS_PREAMBLE}\n\nUser instruction: summarize"
        assert prompt_text == expected
