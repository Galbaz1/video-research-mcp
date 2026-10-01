"""Actual public local AV preparation with only external SDK responses mocked."""

import hashlib
import io
import re
import wave
from pathlib import Path

from fastmcp import Client
from google.genai import types
from jsonschema import validate
import pytest

from tests.native_media_fixtures import digest
from tests.test_media_perceive import response, sdk
from tests.test_media_storyboard import fixed_media, isolated_outputs
from video_research_mcp.config import get_config
from video_research_mcp.tools.media_perceive import media_perceive_server

__all__ = ["fixed_media", "isolated_outputs", "sdk"]


def fixture_request(fixture, **values):
    """Bind unchanged owned fixture bytes and a nonzero source selection."""
    return {"file_path": fixture["path"], "expected_source_sha256": fixture["sha256"],
            "instruction": "List source evidence separately", "start_seconds": 0.2,
            "end_seconds": 1.2, "fps": 5 / 2, "window_seconds": 1,
            "dry_run": False, "authorize_submission": True, **values}


def observed_reply(contents):
    """Mock a claim at the actual labeled sample point, without claiming pixel semantics."""
    label = next(p.text for p in contents.parts if p.text and p.text.startswith("Visible frame"))
    point = float(re.search(r"seconds ([0-9.eE+-]+)", label)[1])
    return response({"summary": "Fixture response", "events": [
        {"modality": "visible", "start_seconds": point, "end_seconds": point,
         "description": "Synthetic provider claim", "frame_indices": [0]}], "abstentions": []})


@pytest.mark.parametrize("name", ["cfr", "vfr", "offset", "rotated"])
async def test_public_measured_source_points_match_actual_sdk_image_and_audio_bytes(name, fixed_media, sdk):
    captured = []

    async def generate(**kwargs):
        captured.append(kwargs["contents"])
        return observed_reply(kwargs["contents"])
    sdk.aio.models.generate_content.side_effect = generate
    fixture = fixed_media[name]
    arguments = fixture_request(fixture, end_seconds=1.16 if name == "vfr" else 1.2)
    async with Client(media_perceive_server) as client:
        tool = (await client.list_tools())[0]
        reply = await client.call_tool("media_perceive", {"request": arguments})
        value = reply.structured_content
        validate(value, tool.output_schema)
    assert value.get("status") == "complete", value
    assert digest(Path(fixture["path"])) == fixture["sha256"]
    window = value["windows"][0]
    points = [f["actual_seconds"] for f in window["frames"]]
    assert all(0.2 <= point < arguments["end_seconds"] for point in points)
    assert value["timeline"][0]["start_seconds"] == pytest.approx(points[0])
    assert not value["execution"]["continuous_watched_coverage"]
    assert window["watched_intervals"] == []
    assert sdk.aio.models.count_tokens.call_args.kwargs["contents"] is captured[0]
    images = [p.inline_data.data for p in captured[0].parts if p.inline_data and p.inline_data.mime_type == "image/png"]
    assert [hashlib.sha256(image).hexdigest() for image in images] == [f["sha256"] for f in window["frames"]]
    sound = [p.inline_data.data for p in captured[0].parts if p.inline_data and p.inline_data.mime_type == "audio/wav"]
    if name == "rotated":
        assert len(sound) == 1
        assert hashlib.sha256(sound[0]).hexdigest() == window["audio"]["artifact"]["sha256"]
        with wave.open(io.BytesIO(sound[0]), "rb") as wav:
            pcm = wav.readframes(wav.getnframes())
            assert wav.getnframes() == window["audio"]["output"]["sample_count"]
        assert hashlib.sha256(pcm).hexdigest() == window["audio"]["output"]["pcm_sha256"]
        assert window["frames"][0]["width"] == 96 and window["frames"][0]["height"] == 160
    else:
        assert sound == [] and window["audio"] is None
    views = Path(get_config().cache_dir) / "media/views"
    assert not list(views.iterdir())
    assert "data:image" not in str(value) and "parts" not in window


async def test_silent_video_cannot_support_a_spoken_claim(fixed_media, sdk):
    sdk.aio.models.generate_content.return_value = response({"summary": "Unsupported speech", "events": [
        {"modality": "spoken", "start_seconds": 0, "end_seconds": 0.1, "description": "Fabricated audio"}]})
    async with Client(media_perceive_server) as client:
        reply = await client.call_tool("media_perceive", {"request": fixture_request(fixed_media["cfr"])}, raise_on_error=False)
    value = reply.structured_content
    assert "error" in value and value["timeline"] == []
    assert value["windows"][0]["status"] == "failed"
    assert value["execution"]["provider_calls"] == 2
    assert not list((Path(get_config().cache_dir) / "media/views").iterdir())


async def test_original_vfr_out_of_source_selection_remains_a_refusal(fixed_media, sdk):
    async with Client(media_perceive_server) as client:
        reply = await client.call_tool("media_perceive", {"request": fixture_request(fixed_media["vfr"])}, raise_on_error=False)
    value = reply.structured_content
    assert "outside the source presentation extent" in value["error"]
    assert value["execution"]["provider_calls"] == 0
    sdk.aio.models.count_tokens.assert_not_awaited()
    sdk.aio.models.generate_content.assert_not_awaited()


async def test_public_nonzero_adjacent_windows_map_both_local_origins(fixed_media, sdk):
    sdk.aio.models.generate_content.side_effect = lambda **kw: observed_reply(kw["contents"])
    async with Client(media_perceive_server) as client:
        reply = await client.call_tool("media_perceive", {"request": fixture_request(
            fixed_media["rotated"], start_seconds=0.1, window_seconds=1, fps=1)})
    value = reply.structured_content
    assert value["status"] == "complete", value
    assert [w["start_seconds"] for w in value["windows"]] == pytest.approx([0.1, 1.1])
    assert [w["end_seconds"] for w in value["windows"]] == pytest.approx([1.1, 1.2])
    assert [e["window_index"] for e in value["timeline"]] == [0, 1]
    assert [e["start_seconds"] for e in value["timeline"]] == pytest.approx([0.1, 1.1])
    assert value["execution"]["provider_calls"] == 4
    assert value["execution"]["audio_transmissions"] == 4
    assert not list((Path(get_config().cache_dir) / "media/views").iterdir())


async def test_source_change_during_count_blocks_actual_generation(fixed_media, sdk, tmp_path):
    original = Path(fixed_media["cfr"]["path"]).read_bytes()
    owned = tmp_path / "mutable-copy.mp4"
    owned.write_bytes(original)

    async def changed(**_):
        owned.write_bytes(original + b"changed")
        return types.CountTokensResponse(total_tokens=12)
    sdk.aio.models.count_tokens.side_effect = changed
    async with Client(media_perceive_server) as client:
        reply = await client.call_tool("media_perceive", {"request": fixture_request(
            {"path": str(owned), "sha256": hashlib.sha256(original).hexdigest()})}, raise_on_error=False)
    assert "error" in reply.structured_content
    assert reply.structured_content["execution"]["provider_calls"] == 1
    sdk.aio.models.generate_content.assert_not_awaited()
    assert not list((Path(get_config().cache_dir) / "media/views").iterdir())
    assert digest(Path(fixed_media["cfr"]["path"])) == fixed_media["cfr"]["sha256"]
