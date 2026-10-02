"""Actual public scene-asset schemas, native storyboard pixels and cleanup controls."""

import asyncio
import base64
import hashlib
import json
import wave
from pathlib import Path
from unittest.mock import AsyncMock

from fastmcp import Client
from jsonschema import validate
import pytest

from tests.native_media_fixtures import digest
from tests.test_audio_fingerprints import tone_source
from tests.test_frame_dedup import gradient_source
from tests.test_media_storyboard import fixed_media, isolated_outputs, source_request
from tests.test_scene_detection import scene_sources
from video_research_mcp.config import get_config
from video_research_mcp.tools.image import image_server
from video_research_mcp.tools.media_scenes import media_scenes_server

__all__ = ["fixed_media", "isolated_outputs", "gradient_source", "scene_sources", "tone_source"]
NAMES = {"video_detect_scenes", "video_storyboard", "video_deduplicate_frames",
         "audio_deduplicate", "audio_clip_export", "video_clip_select"}


async def test_discovery_has_explicit_source_revision_and_local_side_effect_annotations():
    async with Client(media_scenes_server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
    assert set(tools) == NAMES
    for tool in tools.values():
        assert tool.annotations.open_world_hint is False
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.read_only_hint is False
        request = tool.input_schema["properties"]["request"]
        assert "expected_source_sha256" in request["required"]
        assert request["additionalProperties"] is False


@pytest.mark.parametrize("name", sorted(NAMES))
async def test_missing_source_revision_is_rejected_before_dispatch(name):
    async with Client(media_scenes_server) as client:
        reply = await client.call_tool(name, {"request": {"file_path": "unused"}}, raise_on_error=False)
    assert reply.is_error
    assert all(block.type == "text" for block in reply.content)


async def test_public_storyboard_native_bytes_and_separate_manifest_readback(fixed_media):
    request = source_request(fixed_media["offset"], start_seconds=0.2, end_seconds=1.0,
                             columns=2, rows=2)
    async with Client(media_scenes_server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        reply = await client.call_tool("video_storyboard", {"request": request})
        validate(reply.structured_content, tools["video_storyboard"].output_schema)
        assert json.loads(reply.content[0].text) == reply.structured_content
        assert [block.type for block in reply.content] == ["text", "image"]
        metadata = reply.structured_content["metadata"]
        assert hashlib.sha256(base64.b64decode(reply.content[1].data)).hexdigest() == metadata["artifact"]["sha256"]
        assert [tile["label"] for tile in metadata["tiles"]] == [
            "00:00:00.200", "00:00:00.400", "00:00:00.600", "00:00:00.800"
        ]
        assert metadata["source"]["container_start_seconds"] == 3
        text = await client.call_tool("video_storyboard", {"request": request, "include_image": False})
        validate(text.structured_content, tools["video_storyboard"].output_schema)
        assert len(text.content) == 1
        assert text.structured_content["metadata"]["tiles"] == metadata["tiles"]
        assert text.structured_content["native_images"][0]["status"] == "text_only"
    manifest = metadata["manifest"]
    async with Client(image_server) as restarted:
        restored = await restarted.call_tool("image_manifest_read", {
            "manifest_path": manifest["path"], "expected_sha256": manifest["sha256"]
        })
        assert restored.structured_content["manifest"]["labels"] == metadata["labels"]
        assert restored.structured_content["verified"] is True
        Path(metadata["artifact"]["path"]).write_bytes(b"changed storyboard")
        denied = await restarted.call_tool("image_manifest_read", {
            "manifest_path": manifest["path"], "expected_sha256": manifest["sha256"]
        }, raise_on_error=False)
        assert denied.is_error
        assert "identity changed" in denied.structured_content["error"]


async def test_public_whole_video_clip_has_valid_schema_and_full_candidate_clocks(fixed_media):
    async with Client(media_scenes_server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        reply = await client.call_tool("video_clip_select", {
            "request": source_request(fixed_media["cfr"], include_audio=False)
        })
    validate(reply.structured_content, tools["video_clip_select"].output_schema)
    metadata = reply.structured_content["metadata"]
    assert metadata["requested_interval"] == {"start_seconds": 0, "end_seconds": 1.2}
    assert metadata["output"]["frame_count"] == 12
    assert metadata["source_frames"][0]["actual_seconds"] == 0
    assert metadata["source_frames"][-1]["actual_seconds"] == 1.1
    assert metadata["audio"]["included"] is False
    assert len(reply.content) == 1 and reply.structured_content["native_images"] == []


async def test_public_visual_cuts_partition_the_actual_source_and_overflow_is_error(scene_sources):
    source = scene_sources / "offset.mp4"
    args = {"request": {"file_path": str(source), "expected_source_sha256": digest(source),
                        "min_scene_seconds": 0.4}}
    async with Client(media_scenes_server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        reply = await client.call_tool("video_detect_scenes", args)
        validate(reply.structured_content, tools["video_detect_scenes"].output_schema)
        result = reply.structured_content["metadata"]
        assert [cut["actual_seconds"] for cut in result["cuts"]] == pytest.approx([0.8, 1.6, 2.4])
        assert [scene["start_seconds"] for scene in result["scenes"]] == pytest.approx([0, 0.8, 1.6, 2.4])
        assert [scene["end_seconds"] for scene in result["scenes"]] == pytest.approx([0.8, 1.6, 2.4, 3.2])
        assert result["provenance"]["semantic_scenes_verified"] is False
        assert result["coverage"]["watched_intervals"] == []
        failed = await client.call_tool("video_detect_scenes", {
            "request": {**args["request"], "max_cuts": 1}
        }, raise_on_error=False)
        assert failed.is_error
        assert "no complete partition" in failed.structured_content["error"]
        validate(failed.structured_content, tools["video_detect_scenes"].output_schema)


async def test_public_dhash_keeps_all_indices_errors_and_exact_native_frames(gradient_source):
    args = {"request": {"file_path": str(gradient_source), "expected_source_sha256": digest(gradient_source),
                        "times_seconds": [1, 0, 0.5, 99, 0.5], "hamming_threshold": 0},
            "include_image": True}
    async with Client(media_scenes_server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        reply = await client.call_tool("video_deduplicate_frames", args)
    validate(reply.structured_content, tools["video_deduplicate_frames"].output_schema)
    result = reply.structured_content["metadata"]
    assert result["status"] == "partial"
    assert [row["candidate_index"] for row in result["candidates"]] == list(range(5))
    assert result["retained_indices"] == [1, 2]
    assert result["similar_indices"] == [0, 4]
    assert result["error_indices"] == [3]
    assert len(reply.content) == 5
    for block, frame in zip(reply.content[1:], result["frames"]):
        assert block.type == "image"
        assert hashlib.sha256(base64.b64decode(block.data)).hexdigest() == frame["sha256"]
    assert result["candidates"][0]["frame"]["sha256"] != result["candidates"][1]["frame"]["sha256"]
    assert result["provenance"]["identity_equivalence_verified"] is False


async def test_public_mfcc_preserves_repeats_distinct_audio_and_silence_in_denominator(tone_source):
    source, source_sha = tone_source
    args = {"request": {"file_path": str(source), "expected_source_sha256": source_sha,
                        "segments": [{"start_seconds": index + .1, "end_seconds": index + .9}
                                     for index in range(4)]}}
    async with Client(media_scenes_server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        reply = await client.call_tool("audio_deduplicate", args)
    validate(reply.structured_content, tools["audio_deduplicate"].output_schema)
    metadata = reply.structured_content["metadata"]
    assert metadata["counts"] == {"requested": 4, "retained": 2, "similar": 1, "error": 1}
    assert [row["index"] for row in metadata["candidates"]] == list(range(4))
    assert metadata["candidates"][1]["exact_pcm_identity"] is True
    assert metadata["candidates"][1]["duplicate_of"] == 0
    assert metadata["candidates"][2]["score"] < .95
    assert "silence" in metadata["candidates"][3]["error"].lower()
    assert metadata["status"] == "partial"
    assert metadata["feature_method"]["speech_or_ordering_equality_verified"] is False
    assert len(reply.content) == 1 and reply.structured_content["native_images"] == []


async def test_public_audio_whole_and_one_sided_exports_preserve_source_pcm_and_restart(tone_source):
    source, source_sha = tone_source
    args = {"request": {"file_path": str(source), "expected_source_sha256": source_sha}}
    async with Client(media_scenes_server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        whole = await client.call_tool("audio_clip_export", args)
        tail = await client.call_tool("audio_clip_export", {
            "request": {**args["request"], "start_seconds": .125}
        })
    for reply in (whole, tail):
        validate(reply.structured_content, tools["audio_clip_export"].output_schema)
        assert len(reply.content) == 1 and reply.structured_content["native_images"] == []
    first, second = whole.structured_content["metadata"], tail.structured_content["metadata"]
    assert first["output"]["sample_count"] == 64000
    assert second["output"]["sample_count"] == 62000
    assert first["source"]["container_start_seconds"] is None
    assert first["source"]["audio_clock_origin_basis"] == "derived_first_decoded_audio_pts"
    with wave.open(str(source), "rb") as reader:
        original = reader.readframes(64000)
    for metadata, expected in ((first, original), (second, original[4000:])):
        with wave.open(metadata["artifact"]["path"], "rb") as reader:
            pcm = reader.readframes(64000)
        assert pcm == expected
        assert hashlib.sha256(pcm).hexdigest() == metadata["output"]["pcm_sha256"]
    assert first["artifact"]["path"] != second["artifact"]["path"]
    async with Client(image_server) as restarted:
        restored = await restarted.call_tool("image_manifest_read", {
            "manifest_path": first["manifest"]["path"], "expected_sha256": first["manifest"]["sha256"]
        })
        assert restored.structured_content["verified"] is True
        assert restored.structured_content["manifest"]["output"]["pcm_sha256"] == first["output"]["pcm_sha256"]
        Path(first["artifact"]["path"]).write_bytes(b"changed WAV")
        denied = await restarted.call_tool("image_manifest_read", {
            "manifest_path": first["manifest"]["path"], "expected_sha256": first["manifest"]["sha256"]
        }, raise_on_error=False)
        assert denied.is_error and "identity changed" in denied.structured_content["error"]
    assert digest(source) == source_sha


async def test_missing_optional_runtime_is_a_structured_nonretryable_error(monkeypatch, fixed_media):
    monkeypatch.setattr("video_research_mcp.media_storyboard.create_storyboard", AsyncMock(
        side_effect=ImportError("Storyboard requires the optional images extra")
    ))
    async with Client(media_scenes_server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        reply = await client.call_tool("video_storyboard", {
            "request": source_request(fixed_media["cfr"])
        }, raise_on_error=False)
    assert reply.is_error
    assert reply.structured_content["category"] == "DEPENDENCY_MISSING"
    assert reply.structured_content["retryable"] is False
    validate(reply.structured_content, tools["video_storyboard"].output_schema)


@pytest.mark.parametrize("cancel", [False, True])
async def test_public_delivery_failure_or_cancel_removes_only_this_invocation(
    cancel, monkeypatch, fixed_media
):
    import video_research_mcp.tools.media_scenes as tools

    args = {"request": source_request(fixed_media["cfr"], columns=2, rows=1)}
    async with Client(media_scenes_server) as client:
        prior = (await client.call_tool("video_storyboard", args)).structured_content["metadata"]
        base = Path(get_config().cache_dir) / "media" / "views"
        before = {str(path.relative_to(base)): path.read_bytes() for path in base.rglob("*") if path.is_file()}
        directories = set(base.iterdir())
        entered, joined = asyncio.Event(), asyncio.Event()

        async def failed(*unused):
            entered.set()
            try:
                if cancel:
                    await asyncio.Future()
                raise RuntimeError("controlled native delivery failure")
            finally:
                joined.set()

        monkeypatch.setattr(tools, "_result", failed)
        task = asyncio.create_task(client.call_tool("video_storyboard", args, raise_on_error=False))
        await asyncio.wait_for(entered.wait(), 5)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            reply = await task
            assert reply.is_error and "native delivery failure" in reply.structured_content["error"]
        await asyncio.wait_for(joined.wait(), 5)
        assert set(base.iterdir()) == directories
        assert {str(path.relative_to(base)): path.read_bytes() for path in base.rglob("*") if path.is_file()} == before
        assert Path(prior["manifest"]["path"]).is_file()
