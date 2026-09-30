"""Actual public MCP schema and supplied-transcript selection contracts."""

from unittest.mock import AsyncMock

from fastmcp import Client
from jsonschema import validate
import pytest

from tests.test_image_ops import png
from tests.test_native_media_results import metadata
from video_research_mcp.tools.media_read import media_info, media_read_server, video_frame_by_query


@pytest.mark.parametrize("arguments", [
    {"time_seconds": -1}, {"time_seconds": float("nan")},
    {"time_seconds": float("inf")}, {"time_seconds": 0, "max_pixels": True},
    {"time_seconds": 0, "crop_box": [0, 0, 1.5, 1]},
    {"time_seconds": 0, "selection": "nearest_exact"},
])
async def test_public_invalid_point_arguments_fail_before_decode(arguments, monkeypatch):
    decode = AsyncMock()
    monkeypatch.setattr("video_research_mcp.media_frames.frame_at", decode)
    async with Client(media_read_server) as client:
        result = await client.call_tool(
            "video_frame", {"file_path": "/unused.mp4", **arguments}, raise_on_error=False
        )
    assert result.is_error
    decode.assert_not_awaited()


async def test_public_path_length_is_bounded_before_native_decode(monkeypatch):
    decode = AsyncMock()
    monkeypatch.setattr("video_research_mcp.media_frames.frame_at", decode)
    async with Client(media_read_server) as client:
        result = await client.call_tool(
            "video_frame", {"file_path": "a/" * 2049, "time_seconds": 0}, raise_on_error=False
        )
    assert result.is_error
    decode.assert_not_awaited()


async def test_query_selects_earliest_token_match_and_requires_original_digest(tmp_path, monkeypatch):
    value = metadata(png(tmp_path / "source.png"))
    decode = AsyncMock(return_value=value)
    monkeypatch.setattr("video_research_mcp.media_frames.frame_at", decode)
    transcript = {
        "source_sha256": value["source"]["sha256"],
        "segments": [
            {"start_seconds": 0.8, "end_seconds": 1, "text": "CONTROL state ON"},
            {"start_seconds": 0.5, "end_seconds": 0.7, "text": "control STATE on"},
        ],
    }
    async with Client(media_read_server) as client:
        tools = await client.list_tools()
        tool = next(tool for tool in tools if tool.name == "video_frame_by_query")
        assert tool.annotations.open_world_hint is False
        result = await client.call_tool(
            "video_frame_by_query",
            {"file_path": "/source.mp4", "query": "state ON", "transcript": transcript},
        )
    assert not result.is_error
    validate(result.structured_content, tool.output_schema)
    decode.assert_awaited_once_with(
        "/source.mp4", time_seconds=0.5, max_pixels=1_000_000,
        expected_source_sha256=value["source"]["sha256"],
    )
    match = result.structured_content["transcript_match"]
    assert match["segment_index"] == 1
    assert match["matched_tokens"] == ["on", "state"]
    assert match["method"] == "lexical_token_overlap"
    assert match["transcript_status"] == "caller_supplied_unverified"


async def test_zero_query_match_abstains_without_selecting_a_frame(monkeypatch):
    decode = AsyncMock()
    monkeypatch.setattr("video_research_mcp.media_frames.frame_at", decode)
    result = await video_frame_by_query(
        "/source.mp4", "unmentioned", {
            "source_sha256": "a" * 64,
            "segments": [{"start_seconds": 0, "end_seconds": 1, "text": "state on"}],
        },
    )
    assert result.is_error
    assert "No lexical transcript match" in result.structured_content["error"]
    assert [part.type for part in result.content] == ["text"]
    decode.assert_not_awaited()


async def test_query_sha_mismatch_returns_structured_error_without_native_payload(monkeypatch):
    decode = AsyncMock(side_effect=ValueError("Source SHA256 differs from requested source revision"))
    monkeypatch.setattr("video_research_mcp.media_frames.frame_at", decode)
    result = await video_frame_by_query(
        "/source.mp4", "on", {
            "source_sha256": "a" * 64,
            "segments": [{"start_seconds": 0.5, "end_seconds": 0.7, "text": "state on"}],
        },
    )
    assert result.is_error
    assert "SHA256 differs" in result.structured_content["error"]
    assert [part.type for part in result.content] == ["text"]


async def test_missing_optional_binary_has_actionable_dependency_error(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    path = tmp_path / "source.mp4"
    path.write_bytes(b"original owned fixture")
    monkeypatch.setattr("video_research_mcp.media_probe.shutil.which", lambda name: None)
    result = await media_info(str(path))
    assert result.is_error
    assert result.structured_content["category"] == "DEPENDENCY_MISSING"
    assert "install FFmpeg separately" in result.structured_content["hint"]
    assert [part.type for part in result.content] == ["text"]
    assert path.read_bytes() == b"original owned fixture"
    assert not list((tmp_path / "cache/media/views").iterdir())


@pytest.mark.parametrize("stage", ["sheet", "transport", "cancel"])
async def test_failed_combined_operation_removes_only_its_generated_views(stage, tmp_path, monkeypatch, clean_config):
    import asyncio
    from pathlib import Path

    from video_research_mcp.media_image_read import read_image
    from video_research_mcp.tools.media_read import video_frame, video_frames

    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    path = png(tmp_path / "source.png")
    generated = await read_image(str(path))
    directory = Path(generated["frames"][0]["path"]).parent
    kept = directory.parent / "unrelated"
    kept.mkdir()
    (kept / "keep").write_text("untouched")
    if stage == "transport":
        Path(generated["frames"][0]["path"]).write_bytes(b"changed after extraction")
        monkeypatch.setattr("video_research_mcp.media_frames.frame_at", AsyncMock(return_value=generated))
        result = await video_frame(str(path), 0)
        assert result.is_error
    else:
        failure = asyncio.CancelledError() if stage == "cancel" else ValueError("Sheet composition failed")
        monkeypatch.setattr("video_research_mcp.media_frames.sample_frames", AsyncMock(return_value=generated))
        monkeypatch.setattr("video_research_mcp.media_frame_views.contact_sheet", AsyncMock(side_effect=failure))
        if stage == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await video_frames(str(path))
        else:
            result = await video_frames(str(path))
            assert result.is_error
    assert not directory.exists()
    assert (kept / "keep").read_text() == "untouched"
    assert path.read_bytes() == png(tmp_path / "comparison.png").read_bytes()
