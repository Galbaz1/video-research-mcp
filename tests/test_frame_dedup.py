"""Owned exact gradients expose similarity, candidate order and full error denominators."""

import asyncio
import json
import os
import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from tests.native_media_fixtures import digest
from video_research_mcp.config import get_config
from video_research_mcp.media_frame_dedup import deduplicate_frames
from video_research_mcp.media_probe import binary
from video_research_mcp.media_process import run_media_process
from video_research_mcp.models.scene_assets import FrameDedupRequest


@pytest.fixture(autouse=True)
def isolated_views(tmp_path, clean_config, monkeypatch):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("LOCAL_FILE_ACCESS_ROOT", raising=False)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def gradient_source(tmp_path_factory):
    """Freeze known 64-bit hashes before encoding three lossless original9x8 RGB frames."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Owned gradient fixtures require installed FFmpeg/ffprobe")
    root = os.getenv("VISUAL_OWNER_FIXTURE_ROOT")
    directory = Path(root) / "gradients" if root else tmp_path_factory.mktemp("owned-dhash")
    directory.mkdir(parents=True, exist_ok=True)
    declaration = {"pts_seconds": [0, 0.5, 1], "hashes": ["ffffffffffffffff", "0000000000000000", "ffffffffffffffff"],
                   "third_frame": "descending gradient plus10 differs in exact pixels but identical dHash"}
    (directory / "expected-before-generation.json").write_text(json.dumps(declaration))
    pixels = b"".join(bytes((240 - x * 25 + (10 if index == 2 else 0) if index != 1 else x * 25,)) * 3
                      for index in range(3) for _ in range(8) for x in range(9))
    raw = directory / "gradient.rgb"
    raw.write_bytes(pixels)
    path = directory / "gradient.mp4"
    await run_media_process([binary("ffmpeg"), "-v", "error", "-nostdin", "-n", "-threads", "1",
                            "-protocol_whitelist", "file", "-f", "rawvideo", "-pixel_format", "rgb24",
                            "-video_size", "9x8", "-framerate", "2", "-i", str(raw), "-an",
                            "-c:v", "libx264rgb", "-threads", "1", "-crf", "0", "-preset", "ultrafast",
                            "-map_metadata", "-1", str(path)], 20)
    return path


def request(path, times, **values):
    return FrameDedupRequest(file_path=str(path), expected_source_sha256=digest(path),
                             times_seconds=times, **values)


async def test_chronological_greedy_decisions_preserve_original_indices_duplicates_and_errors(gradient_source):
    before = gradient_source.read_bytes()
    result = await deduplicate_frames(request(gradient_source, [1, 0, 0.5, 99, 0.5]))
    candidates = result["candidates"]
    assert [c["candidate_index"] for c in candidates] == list(range(5))
    assert result["decision_order"] == [1, 2, 4, 0, 3]
    assert [c["decision"] for c in candidates] == ["similar", "retained", "retained", "error", "similar"]
    assert [c["representative_index"] for c in candidates] == [1, 1, 2, None, 2]
    assert [c["hamming_distance"] for c in candidates] == [0, 0, 0, None, 0]
    assert candidates[1]["dhash_hex"] == "ffffffffffffffff"
    assert candidates[2]["dhash_hex"] == "0000000000000000"
    assert candidates[0]["dhash_hex"] == "ffffffffffffffff"
    assert candidates[0]["frame"]["sha256"] != candidates[1]["frame"]["sha256"]
    assert result["status"] == "partial" and result["error_indices"] == [3]
    assert result["provenance"]["identity_equivalence_verified"] is False
    assert result["provenance"]["changed_text_preservation_verified"] is False
    assert result["coverage"]["watched_intervals"] == []
    assert all(artifact["mime"] == "image/png" for artifact in result["artifacts"])
    assert gradient_source.read_bytes() == before


async def test_precise_non_grid_time_keeps_actual_frame_pts_and_full_hash(gradient_source):
    result = await deduplicate_frames(request(gradient_source, [0.51, 0.6], hamming_threshold=0))
    first, second = result["candidates"]
    assert first["frame"]["requested_seconds"] == 0.51
    assert first["frame"]["actual_seconds"] == 1
    assert first["frame"]["delta_seconds"] == pytest.approx(0.49)
    assert first["frame"]["original_pts"] == 16384 and first["frame"]["time_base"] == "1/16384"
    assert second["decision"] == "similar" and second["representative_index"] == 0
    for candidate in result["candidates"]:
        frame = candidate["frame"]
        assert frame["sha256"] == digest(Path(frame["path"]))


async def test_default_pixel_reservation_supports_all64_submitted_duplicates(gradient_source):
    result = await deduplicate_frames(request(gradient_source, [0] * 64))
    assert len(result["candidates"]) == len(result["frames"]) == 64
    assert result["retained_indices"] == [0]
    assert result["similar_indices"] == list(range(1, 64))
    assert result["error_indices"] == [] and result["status"] == "complete"
    assert result["limits"]["reserved_artifact_bytes"] <= 8 * 1024 * 1024
    assert len({c["candidate_index"] for c in result["candidates"]}) == 64


async def test_exact_source_end_is_error_candidate_not_clamped_or_dropped(gradient_source):
    result = await deduplicate_frames(request(gradient_source, [1.5, 0]))
    assert len(result["candidates"]) == 2
    assert result["candidates"][0]["decision"] == "error"
    assert result["candidates"][0]["frame"] is None
    assert result["candidates"][1]["decision"] == "retained"


async def test_wrong_digest_fails_before_any_probe_or_decode(gradient_source, monkeypatch):
    process = AsyncMock(side_effect=AssertionError("Stale source reached subprocess"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", process)
    value = request(gradient_source, [0]).model_copy(update={"expected_source_sha256": "0" * 64})
    with pytest.raises(ValueError, match="SHA256"):
        await deduplicate_frames(value)
    assert not process.called


async def test_decode_failure_is_retained_then_later_candidates_still_process(gradient_source, monkeypatch):
    from video_research_mcp import media_frame_dedup as engine

    original = engine.frame_at

    async def controlled(*args, **kwargs):
        if kwargs["time_seconds"] == 0:
            raise RuntimeError("controlled decoder failure")
        return await original(*args, **kwargs)

    monkeypatch.setattr(engine, "frame_at", controlled)
    result = await deduplicate_frames(request(gradient_source, [0, 0.5]))
    assert len(result["candidates"]) == 2
    assert result["candidates"][0]["decision"] == "error" and result["candidates"][0]["error"]
    assert result["candidates"][1]["decision"] == "retained"
    assert result["status"] == "partial" and result["error_indices"] == [0]


async def test_aggregate_reservation_rejects_before_frame_decode(gradient_source, monkeypatch):
    from video_research_mcp import media_frame_dedup as engine

    probe = engine.probe_snapshot

    async def large(owned):
        source = await probe(owned)
        source.update(display_width=1920, display_height=1080)
        return source

    decode = AsyncMock(side_effect=AssertionError("Over-budget frame decode"))
    monkeypatch.setattr(engine, "probe_snapshot", large)
    monkeypatch.setattr(engine, "frame_at", decode)
    with pytest.raises(ValueError, match="aggregate"):
        await deduplicate_frames(request(gradient_source, [0] * 64, max_pixels=1000000))
    assert not decode.called


async def test_changed_source_after_frame_preparation_prevents_success_and_cleans_views(gradient_source, monkeypatch, tmp_path):
    from video_research_mcp import media_frame_dedup as engine

    original = tmp_path / "original.mp4"
    original.write_bytes(gradient_source.read_bytes())
    decode = engine.frame_at

    async def mutate(*args, **kwargs):
        result = await decode(*args, **kwargs)
        original.write_bytes(original.read_bytes() + b"changed")
        return result

    monkeypatch.setattr(engine, "frame_at", mutate)
    with pytest.raises(ValueError, match="changed"):
        await deduplicate_frames(request(original, [0]))
    assert not list((Path(get_config().cache_dir) / "media" / "views").iterdir())
