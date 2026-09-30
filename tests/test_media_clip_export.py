"""Owned fixed-source controls for measured local clip export."""

import json
import os
import shutil
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import ValidationError

from tests.native_media_fixtures import build_fixtures, digest, frame_index
from video_research_mcp import media_clip_export as engine
from video_research_mcp.config import get_config
from video_research_mcp.image_manifest import read_manifest
from video_research_mcp.media_clip_export import export_clip
from video_research_mcp.media_clip_timing import source_audio
from video_research_mcp.media_probe import binary
from video_research_mcp.media_process import run_media_process
from video_research_mcp.models.media_export import ClipExportRequest, ClipExportResult


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def fixed_manifest(tmp_path_factory):
    """Reuse sealed development bytes, or build the same declared portable fixtures once."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Independently installed FFmpeg/ffprobe are required")
    if supplied := os.getenv("NATIVE_MEDIA_FIXTURE_MANIFEST"):
        path = Path(supplied)
        assert digest(path) == "e850edfe4da72f54ebf7b533dd715606998cd0d96aa4b0479af80d80bdfc60eb"
        manifest = json.loads(path.read_text())
    else:
        manifest = await build_fixtures(tmp_path_factory.mktemp("native-clip-fixtures"))
    for fixture in manifest["fixtures"].values():
        assert digest(Path(fixture["path"])) == fixture["sha256"]
    return manifest

@pytest.fixture
def fixture_sources(monkeypatch, tmp_path, clean_config, fixed_manifest):
    """Read unchanged development fixtures; isolate all newly derived artifacts."""
    cache = Path(os.getenv("NATIVE_MEDIA_CLIP_OUTPUT_ROOT", str(tmp_path))) / tmp_path.name / "cache"
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(cache))
    monkeypatch.delenv("LOCAL_FILE_ACCESS_ROOT", raising=False)
    return Path(fixed_manifest["fixtures"]["cfr"]["path"]).parent


def save_receipt(result):
    """Keep component output JSON alongside each retained private artifact."""
    path = Path(result["manifest"]["path"]).parent / "test-result.json"
    path.write_text(json.dumps(result, indent=2) + "\n")


async def export(name, fixture_sources, start=0.2, end=0.8, **kwargs):
    """Validate returned typed results and retain the measured output receipt."""
    suffix = ".mkv" if name == "vfr" else ".mp4"
    request = ClipExportRequest.model_validate({"file_path": str(fixture_sources / (name + suffix)),
                                               "start_seconds": start, "end_seconds": end, **kwargs})
    result = ClipExportResult.model_validate(await export_clip(request)).model_dump()
    save_receipt(result)
    return result


async def test_cropped_clip_has_exact_original_frames_and_verified_encoded_readback(fixture_sources):
    """A cropped short burst retains actual source PTS and verifies encoded frame count."""
    result = await export("cfr", fixture_sources, 0.4, 0.8,
                          crop_box=[32, 36, 96, 24], include_audio=False)
    assert [frame["actual_seconds"] for frame in result["source_frames"]] == pytest.approx([0.4, 0.5, 0.6, 0.7])
    assert result["output"]["frame_count"] == 4
    assert result["output"]["width"] == 96
    assert result["output"]["height"] == 24
    assert result["actual_selected_interval"]["end_seconds"] is None
    assert result["actual_selected_interval"]["last_frame_hold_verified"] is False
    assert result["artifacts"][0]["sha256"] == digest(Path(result["artifacts"][0]["path"]))
    assert result["manifest"]["sha256"] == digest(Path(result["manifest"]["path"]))
    assert result["provenance"] == "extracted_source_clip"


@pytest.mark.parametrize("name, expected", [
    ("cfr", [0.2, 0.3, 0.4, 0.5, 0.6, 0.7]),
    ("offset", [0.2, 0.3, 0.4, 0.5, 0.6, 0.7]),
    ("vfr", [0.28, 0.52, 0.64]),
])
async def test_original_clocks_match_fixed_cfr_vfr_and_nonzero_offset(name, expected, fixture_sources, fixed_manifest):
    """Selected times match independently fixed source PTS, including B-frame presentation order."""
    result = await export(name, fixture_sources, include_audio=False)
    assert [f["actual_seconds"] for f in result["source_frames"]] == pytest.approx(expected)
    original = fixed_manifest["fixtures"][name]
    oracle = [frame for frame in original["oracle"]["frames"] if frame["media_type"] == "video"]
    selected = [frame for frame in oracle
                if 200 <= round(float(frame["best_effort_timestamp_time"]) * 1000) - original["offset_ms"] < 800]
    assert [f["original_pts"] for f in result["source_frames"]] == [int(f["pts"]) for f in selected]
    assert result["output"]["decoded_frame_seconds"] == pytest.approx([value - 0.2 for value in expected], abs=1e-6)
    assert result["source"]["sha256"] == original["sha256"]
    assert digest(Path(original["path"])) == original["sha256"]
    assert result["watched_intervals"] == []


async def test_precise_nongrid_window_retains_initial_delay_and_half_open_boundary(fixture_sources):
    """A .15 request starts at original .2, keeping .05 output delay rather than invented timing."""
    result = await export("cfr", fixture_sources, 0.15, 0.5, include_audio=False)
    assert [f["actual_seconds"] for f in result["source_frames"]] == pytest.approx([0.2, 0.3, 0.4])
    assert result["output"]["first_frame_seconds"] == pytest.approx(0.05, abs=1e-6)
    assert result["requested_interval"] == {"start_seconds": 0.15, "end_seconds": 0.5}


async def test_rotation_and_actual_decoded_audio_timestamps(fixture_sources):
    """Display rotation and actual source/output audio sample clocks are measured separately."""
    result = await export("rotated", fixture_sources, 0.15, 0.8)
    assert (result["source"]["stored_width"], result["source"]["stored_height"]) == (160, 96)
    assert (result["output"]["width"], result["output"]["height"]) == (96, 160)
    audio = result["audio"]
    assert audio["included"] is True
    assert audio["source_decoded"]["first_seconds"] == pytest.approx(0.15, abs=1 / 8000)
    assert audio["source_decoded"]["end_seconds"] == pytest.approx(0.8, abs=1 / 8000)
    assert audio["output_decoded"]["decoded_frame_count"] > 0
    assert audio["output_decoded"]["end_seconds"] >= audio["output_decoded"]["last_seconds"]
    assert audio["source_av_start_delta_seconds"] == pytest.approx(0.05, abs=1 / 8000)
    assert abs(audio["timestamp_start_delta_error_seconds"]) <= 1 / 8000
    assert audio["perceptual_sync_verified"] is False


async def test_decoded_output_visual_frames_are_the_fixed_original_burst(fixture_sources):
    """Actual decoded pixels preserve source barcode indices across the short changed-state burst."""
    result = await export("cfr", fixture_sources, 0.4, 0.8, include_audio=False)
    command = [binary("ffmpeg"), "-v", "error", "-nostdin", "-threads", "1", "-protocol_whitelist", "file",
               "-i", result["artifacts"][0]["path"], "-an", "-frames:v", "4", "-fps_mode", "passthrough",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    rgb, _ = await run_media_process(command, 10)
    size = 160 * 96 * 3
    assert len(rgb) == size * 4
    assert [frame_index(rgb[index * size:(index + 1) * size], 160) for index in range(4)] == [4, 5, 6, 7]


async def test_manifest_restart_readback_then_artifact_tamper_rejection(fixture_sources):
    """A new readback validates persisted original/artifact hashes and rejects edited encoded bytes."""
    result = await export("cfr", fixture_sources, include_audio=False)
    restored = await read_manifest(result["manifest"]["path"], result["manifest"]["sha256"])
    assert restored["verified"] is True
    assert restored["source_frames"] == result["source_frames"]
    assert restored["output"] == result["output"]
    artifact = Path(result["artifacts"][0]["path"])
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="identity changed"):
        await read_manifest(result["manifest"]["path"], result["manifest"]["sha256"])


async def test_restart_rejects_changed_original_and_wrong_manifest_digest(fixture_sources, tmp_path):
    """Original source identity and explicit manifest commitment remain necessary after restart."""
    source = tmp_path / "source.mp4"
    source.write_bytes((fixture_sources / "cfr.mp4").read_bytes())
    result = await export_clip(ClipExportRequest(file_path=str(source), start_seconds=0.2, end_seconds=0.8))
    with pytest.raises(ValueError, match="SHA256"):
        await read_manifest(result["manifest"]["path"], "0" * 64)
    source.write_bytes(source.read_bytes() + b"changed-original")
    with pytest.raises(ValueError, match="identity changed"):
        await read_manifest(result["manifest"]["path"], result["manifest"]["sha256"])


@pytest.mark.parametrize("values", [
    {"start_seconds": float("nan")}, {"end_seconds": float("inf")},
    {"start_seconds": -1}, {"end_seconds": 0.2}, {"end_seconds": 61},
    {"max_pixels": 1_000_001}, {"max_pixels": True}, {"crop_box": [True, 0, 10, 10]},
    {"expected_source_sha256": "short"},
])
def test_request_rejects_nonfinite_unbounded_or_ambiguous_inputs(values):
    """Public request constraints fail before decoding or creating artifacts."""
    request = {"file_path": "unused.mp4", "start_seconds": 0.2, "end_seconds": 0.8, **values}
    with pytest.raises(ValidationError):
        ClipExportRequest.model_validate(request)


@pytest.mark.parametrize("values, message", [
    ({"end_seconds": 1.3}, "outside"), ({"crop_box": [150, 0, 20, 20]}, "outside"),
    ({"max_pixels": 1}, "two pixels"), ({"expected_source_sha256": "0" * 64}, "SHA256"),
])
async def test_source_bounds_crop_and_revision_fail_closed(values, message, fixture_sources):
    """Unsupported source requests retain no successful clip or manifest path."""
    with pytest.raises((ValueError, PermissionError), match=message):
        await export("cfr", fixture_sources, include_audio=False, **values)
    directory = Path(get_config().cache_dir) / "media" / "views"
    assert not directory.exists() or not list(directory.iterdir())


async def test_auto_scaled_even_floor_keeps_original_pts_and_pixel_budget(fixture_sources):
    """Codec-compatible even dimensions are an explicit floor of the bounded automatic scale."""
    result = await export("cfr", fixture_sources, max_pixels=10000, include_audio=False)
    assert (result["output"]["width"], result["output"]["height"]) == (128, 76)
    assert result["limits"]["scale"] == {"unrounded_dimensions": [129, 77],
                                         "output_dimensions": [128, 76],
                                         "rounding": "floor_to_even_without_padding"}
    assert [f["actual_seconds"] for f in result["source_frames"]] == pytest.approx([0.2, 0.3, 0.4, 0.5, 0.6, 0.7])
    assert result["limits"]["operation_timeout_seconds"] == get_config().media_acquire_timeout_seconds
    assert result["limits"]["process_rss_bound"] is None


async def test_odd_display_crop_is_explicitly_scaled_without_padding(fixture_sources):
    """A declared odd crop stays the requested source region and produces measured even codec dimensions."""
    result = await export("cfr", fixture_sources, crop_box=[32, 36, 95, 23], include_audio=False)
    assert result["crop_box"] == [32, 36, 95, 23]
    assert (result["output"]["width"], result["output"]["height"]) == (94, 22)
    assert result["limits"]["scale"]["rounding"] == "floor_to_even_without_padding"


@pytest.mark.parametrize("change, message", [
    ({"r_frame_rate": "60/1"}, "30 FPS"),
    ({"r_frame_rate": "30/1", "avg_frame_rate": "30/1"}, "256 frame"),
])
async def test_declared_rate_and_window_budget_reject_before_decoder(change, message, monkeypatch, fixture_sources):
    """Unsupported declared media cannot reach an expensive decoder pass."""
    probe = engine.probe_snapshot

    async def controlled(owned):
        source = await probe(owned)
        source["presentation_end_seconds"] = 60
        source["streams"][0].update(change)
        return source

    async def denied(*args, **kwargs):
        pytest.fail("Out-of-contract source reached decoding")

    monkeypatch.setattr(engine, "probe_snapshot", controlled)
    monkeypatch.setattr(engine, "run_media_process", denied)
    with pytest.raises(ValueError, match=message):
        await export("cfr", fixture_sources, 0, 10, include_audio=False)
    assert not list((Path(get_config().cache_dir) / "media" / "views").iterdir())


@pytest.mark.parametrize("field, value", [("sample_rate", "96000"), ("channels", 8)])
async def test_audio_allocation_bound_rejects_before_encoder(field, value, monkeypatch, fixture_sources):
    """Audio rate/channel metadata must fit the explicit allocation contract."""
    probe = engine.probe_snapshot

    async def controlled(owned):
        source = await probe(owned)
        next(s for s in source["streams"] if s["codec_type"] == "audio")[field] = value
        return source

    monkeypatch.setattr(engine, "probe_snapshot", controlled)
    with pytest.raises(ValueError, match="48 kHz"):
        await export("rotated", fixture_sources)
    assert not list((Path(get_config().cache_dir) / "media" / "views").iterdir())


@pytest.mark.parametrize("record", [
    b"metadata: [Parsed_ashowinfo_0 @ abc] n:0 pts:0 pts_time:0 rate:8000 nb_samples:100\n",
    b"[Parsed_ashowinfo_0 @ abc] n:0 pts:0 pts_time:1 rate:8000 nb_samples:100\n",
    b"[Parsed_ashowinfo_0 @ abc] n:1 pts:0 pts_time:0 rate:8000 nb_samples:100\n",
    b"[Parsed_ashowinfo_0 @ abc] n:0 pts:0 pts_time:0 rate:8000 nb_samples:100\n"
    b"[Parsed_ashowinfo_1 @ def] n:1 pts:100 pts_time:0.0125 rate:8000 nb_samples:100\n",
])
def test_source_audio_rejects_fake_ambiguous_or_inconsistent_decoder_clocks(record):
    """Untrusted lookalikes cannot establish actual decoded audio provenance."""
    with pytest.raises(ValueError):
        source_audio(record, 0, 0, 1)


async def test_missing_source_produces_no_owned_artifact(fixture_sources, tmp_path):
    """Missing local bytes fail before any clip path can be returned."""
    with pytest.raises(FileNotFoundError):
        await export_clip(ClipExportRequest(file_path=str(tmp_path / "missing.mp4"),
                                          start_seconds=0.2, end_seconds=0.8))
    assert not (Path(get_config().cache_dir) / "media" / "views").exists()


async def test_source_mutation_during_encode_removes_all_derived_outputs(monkeypatch, fixture_sources, tmp_path):
    """A changed original prevents durable success even though the frozen snapshot encoded correctly."""
    source = tmp_path / "source.mp4"
    source.write_bytes((fixture_sources / "cfr.mp4").read_bytes())
    original = engine.run_media_process

    async def mutate(command, timeout):
        output = await original(command, timeout)
        if command[-1].endswith("clip.mp4"):
            source.write_bytes(source.read_bytes() + b"changed")
        return output

    monkeypatch.setattr(engine, "run_media_process", mutate)
    with pytest.raises(ValueError, match="changed"):
        await export_clip(ClipExportRequest(file_path=str(source), start_seconds=0.2, end_seconds=0.8))
    assert not list((Path(get_config().cache_dir) / "media" / "views").iterdir())


async def test_ffmpeg_early_file_size_exit_cannot_claim_complete(monkeypatch, fixture_sources):
    """Actual file-size-limited encoding must fail selected-frame or decoded output completeness."""
    original = engine.run_media_process

    async def limited(command, timeout):
        command = list(command)
        if command[-1].endswith("clip.mp4"):
            command[command.index("-fs") + 1] = "1200"
        return await original(command, timeout)

    monkeypatch.setattr(engine, "run_media_process", limited)
    with pytest.raises(ValueError, match="exactly|truncated|timing"):
        await export("cfr", fixture_sources, 0, 1.2, include_audio=False)
    assert not list((Path(get_config().cache_dir) / "media" / "views").iterdir())


async def test_process_failure_removes_owned_snapshot_and_output(monkeypatch, fixture_sources):
    """Encoder failure publishes no retained source snapshot or success manifest."""
    original = engine.run_media_process

    async def failed(command, timeout):
        if command[-1].endswith("clip.mp4"):
            Path(command[-1]).write_bytes(b"partial")
            raise RuntimeError("controlled encoder failure")
        return await original(command, timeout)

    monkeypatch.setattr(engine, "run_media_process", failed)
    with pytest.raises(RuntimeError, match="controlled"):
        await export("cfr", fixture_sources)
    assert not list((Path(get_config().cache_dir) / "media" / "views").iterdir())
