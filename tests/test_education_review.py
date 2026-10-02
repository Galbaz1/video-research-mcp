"""Complete output/readback gates and controlled measured-evidence mutation regressions."""

import copy
import hashlib
import json
from pathlib import Path
import struct
import threading
import time

import pytest

from tests.test_education_domain import spec_fixture
from tests.test_education_workflow import inputs, native, probe_reply, wav_bytes
from video_research_mcp import education, education_review as review
from video_research_mcp.education_frames import authored_frames
from video_research_mcp.education_native import inspect_video
from video_research_mcp.footage_edit_native import NativeWork
from video_research_mcp.models.education import LessonSpec

__all__ = ["inputs", "native"]


@pytest.mark.parametrize("name", ["decoded.rgb", "decoded.wav"])
async def test_evidence_mutated_after_measurement_before_file_commit_cannot_pass(name, inputs, native, monkeypatch):
    """Reproduce root integration's measured-derived-evidence drift without any native job."""
    original, changed = review.file_record, False
    def record(path, directory, maximum, cancelled, deadline):
        nonlocal changed
        if Path(path).name == name and not changed:
            with Path(path).open("r+b") as writer:
                offset = 0 if name == "decoded.rgb" else 44
                writer.seek(offset)
                writer.write(b"\x7f")
            changed = True
        return original(path, directory, maximum, cancelled, deadline)
    monkeypatch.setattr(review, "file_record", record)
    with pytest.raises(ValueError, match="measured|evidence|identity"):
        await education.build_lesson(**inputs)
    assert changed and not Path(inputs["output_directory"]).exists()


@pytest.mark.parametrize("change", ["count", "clock", "duration", "grid", "codec", "audio_count", "audio_clock", "nan"])
def test_incomplete_or_malformed_actual_output_clocks_are_terminal(change):
    measured = {"output": {"frame_count": 72, "decoded_frame_seconds": [i / 12 for i in range(72)],
                          "duration_seconds": 6, "width": 640, "height": 360, "video_codec": "h264"},
                "audio": {"sample_count": 288000, "sample_rate": 48000, "duration_seconds": 6,
                          "first_seconds": 0, "end_seconds": 6}}
    if change == "count":
        measured["output"]["frame_count"] = 71
    elif change == "clock":
        measured["output"]["decoded_frame_seconds"][35] += 0.01
    elif change == "duration":
        measured["output"]["duration_seconds"] = 5.9
    elif change == "grid":
        measured["output"]["width"] = 639
    elif change == "codec":
        measured["output"]["video_codec"] = "ffv1"
    elif change == "audio_count":
        measured["audio"]["sample_count"] = 287999
    elif change == "audio_clock":
        measured["audio"]["first_seconds"] = 0.5
    else:
        measured["audio"]["duration_seconds"] = float("nan")
    with pytest.raises(ValueError):
        review.clock_gate(measured)


async def test_actual_native_metadata_sums_decoded_audio_samples(native, monkeypatch, tmp_path):
    import video_research_mcp.education_native as module
    async def measured(*_):
        return {"output": {}, "audio": {"first_seconds": 0, "end_seconds": 6}}
    monkeypatch.setattr(module, "decoded", measured)
    work = NativeWork(time.monotonic() + 120)
    await work.admit()
    result = await inspect_video(tmp_path / "fake.mp4", work)
    assert result["audio"]["sample_count"] == 288000 and result["audio"]["duration_seconds"] == 6


@pytest.mark.parametrize("field,value", [("codec_name", "aac"), ("channels", 2), ("sample_rate", "44100")])
async def test_lossy_or_reformatted_output_audio_refuses(field, value, native, monkeypatch, tmp_path):
    import video_research_mcp.education_native as module
    info = probe_reply()
    info["streams"][1][field] = value
    async def run(*_):
        return json.dumps(info).encode(), b""
    async def measured(*_):
        return {"output": {}, "audio": {"first_seconds": 0, "end_seconds": 6}}
    monkeypatch.setattr(module, "decoded", measured)
    work = NativeWork(time.monotonic() + 120)
    work.run = run
    with pytest.raises(ValueError, match="lossless ALAC"):
        await inspect_video(tmp_path / "fake.mp4", work)


def test_full_riff_and_json_structure_refuse_truncated_extra_or_ambiguous_bytes():
    body = wav_bytes()
    review.riff_gate(body)
    for bad in [body[:-1], body + b"hidden", body[:4] + struct.pack("<I", 12) + body[8:]]:
        with pytest.raises(ValueError):
            review.riff_gate(bad)
    for bad in [b'{"status":"complete","status":"failed"}', b'{"x":NaN}']:
        with pytest.raises(ValueError):
            review.strict_json(bad)


@pytest.mark.parametrize("mutation", ["glyph", "curve", "circuit", "caption", "missing"])
def test_changed_actual_authored_pixels_or_missing_scene_fail_source_output_gate(mutation, tmp_path):
    from PIL import Image
    spec = LessonSpec.model_validate(spec_fixture())
    cancelled, deadline = threading.Event(), time.monotonic() + 120
    frames = authored_frames(spec, tmp_path, cancelled, deadline)
    if mutation == "missing":
        frames = frames[:48]
    else:
        number = 0 if mutation == "glyph" else 24 if mutation == "curve" else 48 if mutation == "circuit" else 0
        path = tmp_path / frames[number]["path"]
        with Image.open(path) as image:
            pixel = (50, 36) if mutation == "glyph" else (400, 200) if mutation == "curve" else (160, 220) if mutation == "circuit" else (40, 294)
            image.putpixel(pixel, (255, 0, 255))
            image.save(path)
        frames[number]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        frames[number]["bytes"] = path.stat().st_size
    with pytest.raises(ValueError):
        review.authored_gate(spec, tmp_path, frames, cancelled, deadline)


def test_unqualified_all_skipped_or_mutated_authored_claims_cannot_satisfy_population(tmp_path):
    cancelled, deadline = threading.Event(), time.monotonic() + 120
    spec = LessonSpec.model_validate(spec_fixture())
    frames = authored_frames(spec, tmp_path, cancelled, deadline)
    changed = copy.deepcopy(frames)
    changed[0]["pixel_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="source clock/domain"):
        review.authored_gate(spec, tmp_path, changed, cancelled, deadline)
    with pytest.raises(ValueError, match="72-frame"):
        review.authored_gate(spec, tmp_path, [], cancelled, deadline)


async def test_changed_committed_decoded_raw_or_audio_on_restart_refuses_before_native(inputs, native):
    result = await education.build_lesson(**inputs)
    directory = Path(result["directory"])
    path = directory / "decoded.rgb"
    with path.open("r+b") as writer:
        writer.write(b"\x7f")
    native["calls"].clear()
    with pytest.raises(ValueError, match="committed artifact"):
        await education.check_lesson(directory, result["receipt"]["sha256"])
    assert native["calls"] == []


async def test_omitted_applicable_source_gate_is_not_accepted_even_with_new_external_hash(inputs, native):
    result = await education.build_lesson(**inputs)
    path = Path(result["receipt"]["path"])
    receipt = json.loads(path.read_text())
    del receipt["source_domain"]["gates"]["circuit"]
    body = json.dumps(receipt).encode()
    path.write_bytes(body)
    native["calls"].clear()
    with pytest.raises(ValueError, match="applicable checks were omitted"):
        await education.check_lesson(result["directory"], hashlib.sha256(body).hexdigest())
    assert native["calls"] == []
