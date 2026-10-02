"""Tests for the shared video analysis pipeline."""

from __future__ import annotations

import hashlib
import json
from unittest.mock import AsyncMock, patch

from google.genai import types

import pytest

from video_research_mcp.models.video import VideoResult
from video_research_mcp.tools.video_core import (
    _ANALYSIS_PREAMBLE,
    _enrich_prompt,
    analyze_video,
)


@pytest.fixture(autouse=True)
def _offline_optional_storage(mock_weaviate_disabled):
    """Core contract fixtures never connect to the optional external store."""


def _make_content(text: str = "test") -> types.Content:
    return types.Content(parts=[types.Part(text=text)])


def _make_video_content(text: str = "test") -> types.Content:
    """Content with a file_data part + text part (mimics real video content)."""
    return types.Content(
        parts=[
            types.Part(file_data=types.FileData(file_uri="https://example.com/vid")),
            types.Part(text=text),
        ]
    )


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
    async def test_legacy_remote_cache_is_not_replayed(
        self, mock_gemini_client, tmp_path, monkeypatch
    ):
        """A URL label and historical answer do not prove current source freshness."""
        from video_research_mcp import cache

        monkeypatch.setattr(cache, "_cache_dir", lambda: tmp_path)
        cache.cache_path("cached_id", "video_analyze", "test-model", instruction="test").write_text(
            json.dumps({"analysis": {"title": "Cached"}})
        )
        mock_gemini_client["generate_structured"].return_value = VideoResult(title="Fresh")

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

        assert result["title"] == "Fresh"
        assert result.get("cached") is not True
        mock_gemini_client["generate_structured"].assert_called_once()
        mock_gemini_client["generate"].assert_not_called()


def _local_request(path, text="summarize", metadata=None):
    body = path.read_bytes()
    part = types.Part(inline_data=types.Blob(data=body, mime_type="video/mp4"))
    if metadata is not None:
        part.video_metadata = types.VideoMetadata(**metadata)
    return types.Content(parts=[part, types.Part(text=text)]), hashlib.sha256(body).hexdigest()


async def test_actual_core_reuses_same_byte_alias_and_relabels_source(
    tmp_path, monkeypatch, mock_gemini_client
):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "original.mp4"
    source.write_bytes(b"owned cache fixture")
    contents, digest = _local_request(source)
    mock_gemini_client["generate_structured"].return_value = VideoResult(title="Owned")
    first = await analyze_video(
        contents,
        instruction="summarize",
        content_id=digest,
        source_label=str(source),
        local_filepath=str(source),
    )
    alias = tmp_path / "renamed.mp4"
    source.rename(alias)
    second = await analyze_video(
        contents,
        instruction="summarize",
        content_id=digest,
        source_label=str(alias),
        local_filepath=str(alias),
    )
    assert first["title"] == second["title"] == "Owned"
    assert second["cached"] is True
    assert second["source"] == str(alias)
    assert first["source_sha256"] == second["source_sha256"] == digest
    assert first["source_revision"] == second["source_revision"] == "sha256:" + digest
    assert first["source_freshness"] == second["source_freshness"] == "fresh"
    mock_gemini_client["generate_structured"].assert_called_once()


async def test_model_cannot_promote_unknown_remote_source_to_fresh(mock_gemini_client):
    mock_gemini_client["generate"].return_value = json.dumps(
        {
            "source_sha256": "forged",
            "source_revision": "forged",
            "source_freshness": "fresh",
            "source": "forged source",
        }
    )
    label = "https://example.com/unfetched"
    result = await analyze_video(
        _make_content(),
        instruction="summarize",
        content_id="unverified-id",
        source_label=label,
        output_schema={"type": "object"},
        use_cache=False,
    )
    assert result["source"] == label
    assert result["source_sha256"] is None
    assert result["source_revision"] is None
    assert result["source_freshness"] == "unknown"


async def test_opaque_file_api_part_remains_unknown_without_result_cache_io(
    tmp_path, monkeypatch, mock_gemini_client
):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "source.mp4"
    source.write_bytes(b"local bytes do not prove opaque uploaded bytes")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    mock_gemini_client["generate_structured"].return_value = VideoResult(title="Available")
    with (
        patch(
            "video_research_mcp.tools.video_core.cache_load", side_effect=AssertionError("no read")
        ),
        patch(
            "video_research_mcp.tools.video_core.cache_save", side_effect=AssertionError("no write")
        ),
    ):
        result = await analyze_video(
            _make_video_content(),
            instruction="summarize",
            content_id=digest,
            source_label=str(source),
            local_filepath=str(source),
        )
    assert result["title"] == "Available"
    assert result["source"] == str(source)
    assert result["source_sha256"] is None and result["source_revision"] is None
    assert result["source_freshness"] == "unknown"
    mock_gemini_client["generate_structured"].assert_called_once()


@pytest.mark.parametrize("changed", ["schema", "thinking", "metadata", "window"])
async def test_actual_core_request_changes_do_not_collide(
    tmp_path, monkeypatch, mock_gemini_client, changed
):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "source.mp4"
    source.write_bytes(b"owned cache fixture")
    contents, digest = _local_request(source)
    mock_gemini_client["generate_structured"].return_value = VideoResult(title="Owned")
    mock_gemini_client["generate"].return_value = '{"custom": true}'
    options = {
        "instruction": "summarize",
        "content_id": digest,
        "source_label": str(source),
        "local_filepath": str(source),
    }
    await analyze_video(contents, **options)
    if changed == "schema":
        options["output_schema"] = {"type": "object", "properties": {"custom": {"type": "boolean"}}}
    elif changed == "thinking":
        options["thinking_level"] = "low"
    elif changed == "metadata":
        options["metadata_context"] = "Original source metadata revision two"
    else:
        contents, _ = _local_request(
            source, metadata={"start_offset": "1s", "end_offset": "2s", "fps": 1.0}
        )
    second = await analyze_video(contents, **options)
    assert second.get("cached") is not True
    assert (
        mock_gemini_client["generate_structured"].call_count
        + mock_gemini_client["generate"].call_count
        == 2
    )
    assert len(list((tmp_path / "cache").glob("v2_*.json"))) == 2


async def test_comparison_bypass_reads_and_writes_no_result_or_identity_cache(
    tmp_path, monkeypatch, mock_gemini_client
):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "source.mp4"
    source.write_bytes(b"owned cache fixture")
    contents, digest = _local_request(source)
    mock_gemini_client["generate_structured"].return_value = VideoResult(title="Owned")
    with (
        patch(
            "video_research_mcp.tools.video_core.cache_load", side_effect=AssertionError("no read")
        ),
        patch(
            "video_research_mcp.tools.video_core.cache_save", side_effect=AssertionError("no write")
        ),
    ):
        await analyze_video(
            contents,
            instruction="summarize",
            content_id=digest,
            source_label=str(source),
            local_filepath=str(source),
            use_cache=False,
        )
    assert not (tmp_path / "cache").exists()


async def test_stale_prepared_source_stops_before_cache_or_provider(
    tmp_path, monkeypatch, mock_gemini_client
):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original bytes")
    contents, digest = _local_request(source)
    source.write_bytes(b"changed bytes")
    with pytest.raises(ValueError, match="changed"):
        await analyze_video(
            contents,
            instruction="summarize",
            content_id=digest,
            source_label=str(source),
            local_filepath=str(source),
        )
    mock_gemini_client["generate_structured"].assert_not_called()


async def test_inline_snapshot_cannot_be_mislabeled_with_current_path_digest(
    tmp_path, monkeypatch, mock_gemini_client
):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "source.mp4"
    source.write_bytes(b"prepared original bytes")
    contents, _ = _local_request(source)
    source.write_bytes(b"changed original bytes")
    current_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="Prepared video bytes changed"):
        await analyze_video(
            contents,
            instruction="summarize",
            content_id=current_digest,
            source_label=str(source),
            local_filepath=str(source),
        )
    mock_gemini_client["generate_structured"].assert_not_called()
    assert not list((tmp_path / "cache").glob("v2_*.json"))


async def test_source_mutation_during_generation_rejects_result_and_cache(
    tmp_path, monkeypatch, mock_gemini_client
):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "source.mp4"
    source.write_bytes(b"prepared original bytes")
    contents, digest = _local_request(source)

    async def mutate_source(*args, **kwargs):
        source.write_bytes(b"changed during generation")
        return VideoResult(title="Unusable after mutation")

    mock_gemini_client["generate_structured"].side_effect = mutate_source
    with patch(
        "video_research_mcp.weaviate_store.store_video_analysis", new_callable=AsyncMock
    ) as store:
        with pytest.raises(ValueError, match="changed during analysis"):
            await analyze_video(
                contents,
                instruction="summarize",
                content_id=digest,
                source_label=str(source),
                local_filepath=str(source),
            )
        store.assert_not_awaited()
    assert not list((tmp_path / "cache").glob("v2_*.json"))


async def test_bounded_execution_omits_optional_store_and_graph(mock_gemini_client):
    mock_gemini_client["generate_structured"].return_value = VideoResult(title="Bounded")
    with (
        patch("video_research_mcp.execution_budget.current_budget", return_value=object()),
        patch(
            "video_research_mcp.weaviate_store.store_video_analysis", new_callable=AsyncMock
        ) as store,
        patch(
            "video_research_mcp.weaviate_store.extract_and_store_graph", new_callable=AsyncMock
        ) as graph,
    ):
        await analyze_video(
            _make_content(),
            instruction="summarize",
            content_id="offline-unknown",
            source_label="https://example.com/offline-unknown",
            use_cache=False,
        )
    store.assert_not_awaited()
    graph.assert_not_awaited()


@pytest.mark.asyncio
async def test_passes_local_media_fields_to_store(mock_gemini_client):
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
