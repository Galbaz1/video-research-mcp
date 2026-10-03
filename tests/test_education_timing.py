"""Finite measured-clock controls with explicitly synthetic PCM, never a speech claim."""

import asyncio
import copy
import hashlib
import json
import re
import shutil
import struct
import subprocess
import threading
import time
import wave
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.test_education_domain import spec_fixture
from tests.test_education_workflow import digest, native, wav_bytes
from video_research_mcp import education, education_audio
from video_research_mcp.education_frames import authored_frames
from video_research_mcp.education_review import authored_gate, riff_gate
from video_research_mcp.education_timing import frame_schedule, timeline_from_counts
from video_research_mcp.models.education import MeasuredLessonSpec

__all__ = ["native"]


def measured_inputs(parent, counts=(4501, 7003, 5009)):
    """Commit independently supplied non-frame-aligned scene PCM with distinct bytes."""
    data = spec_fixture()
    data["schema_version"] = 2
    data["narration_segments"] = []
    for index, (scene, caption, count) in enumerate(zip(data["storyboard"]["scenes"], data["script"]["captions"], counts, strict=True)):
        for item in (scene, caption):
            del item["start_seconds"], item["end_seconds"]
        body = wav_bytes(count)
        body = body[:44] + struct.pack("<h", index * 17 - 100) * count
        path = parent / f'{scene["id"]}.wav'
        path.write_bytes(body)
        data["narration_segments"].append({"scene_id": scene["id"], "path": path.name, "sha256": digest(path)})
    source = parent / "measured.json"
    source.write_bytes((json.dumps(data, ensure_ascii=False) + "\n").encode())
    return {"spec_path": str(source), "expected_spec_sha256": digest(source), "output_directory": str(parent / "result")}


async def validate(inputs):
    return await education.validate_lesson(inputs["spec_path"], inputs["expected_spec_sha256"])


async def test_measured_input_admission_binds_exact_scene_pcm_without_native(tmp_path, clean_config, native):
    """GIVEN three fractional WAVs WHEN admitted THEN clocks come from every actual sample."""
    inputs = measured_inputs(tmp_path, (148001, 111007, 96001))
    result = await validate(inputs)
    audio = result["audio"]
    assert audio["frames"] == 355009 and audio["duration_seconds"] == 355009 / 48000
    assert audio["timeline"]["frame_count"] == 89
    assert [(s["start_sample"], s["end_sample"]) for s in audio["timeline"]["scenes"]] == [(0, 148001), (148001, 259008), (259008, 355009)]
    assert [s["visual_delay_samples"] for s in audio["timeline"]["scenes"]] == [0, 3999, 992]
    assert audio["timeline"]["video_tail_samples"] == 991
    pcm = b"".join((tmp_path / f"{name}.wav").read_bytes()[44:] for name in ("triangle", "curve", "circuit"))
    assert audio["pcm_sha256"] == hashlib.sha256(pcm).hexdigest()
    assert native["calls"] == [] and not Path(inputs["output_directory"]).exists()
    assert result["source_domain"]["gates"]["captions"]["timing_basis"] == "measured_whole_scene_segments"
    assert result["unverified"]["caption_speech_alignment_verified"] is False


async def test_relative_segments_use_spec_directory_inside_access_root(tmp_path, clean_config, native, monkeypatch):
    """GIVEN a foreign CWD WHEN relative segments are admitted THEN only their actual paths are fenced."""
    root = tmp_path / "allowed"
    root.mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    inputs = measured_inputs(root)
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(root))
    monkeypatch.chdir(foreign)
    result = await validate(inputs)
    assert [s["path"] for s in result["audio"]["segments"]] == [str(root / f"{name}.wav") for name in ("triangle", "curve", "circuit")]
    assert result["audio"]["frames"] == 16513
    assert native["calls"] == []


async def test_segment_uri_refused_even_when_normalized_local_lookalike_exists(tmp_path, clean_config, native):
    """GIVEN a local URI lookalike WHEN admitting a URI THEN path normalization cannot admit it."""
    inputs = measured_inputs(tmp_path)
    data = json.loads(Path(inputs["spec_path"]).read_bytes())
    lookalike = tmp_path / "https:" / "example.com" / "audio.wav"
    lookalike.parent.mkdir(parents=True)
    lookalike.write_bytes((tmp_path / "triangle.wav").read_bytes())
    data["narration_segments"][0]["path"] = "https://example.com/audio.wav"
    Path(inputs["spec_path"]).write_text(json.dumps(data))
    inputs["expected_spec_sha256"] = digest(Path(inputs["spec_path"]))
    with pytest.raises(PermissionError, match="not URIs"):
        await validate(inputs)
    assert native["calls"] == []


async def test_measured_whole_caller_build_restart_preserves_segments_source_and_pcm(tmp_path, clean_config, native):
    """GIVEN measured inputs WHEN built/reopened with an external hash THEN exact originals rejoin."""
    inputs = measured_inputs(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    result = await education.build_lesson(**inputs)
    output = Path(result["directory"])
    receipt = json.loads((output / "receipt.json").read_bytes())
    assert receipt["schema_version"] == 2 and len(receipt["frames"]) == 5
    assert [f["scene_id"] for f in receipt["frames"]] == ["triangle", "triangle", "curve", "circuit", "circuit"]
    assert [f["timeline_sample"] for f in receipt["frames"]] == [0, 4000, 8000, 12000, 16000]
    assert receipt["audio"]["timeline"]["video_tail_samples"] == 3487
    for scene in ("triangle", "curve", "circuit"):
        assert (output / f"segment-{scene}.wav").read_bytes() == before[f"{scene}.wav"]
    assert (output / "source.json").read_bytes() == before["measured.json"]
    with wave.open(str(output / "narration.wav"), "rb") as reader:
        assert reader.getnframes() == 16513
        assert reader.readframes(16514) == b"".join(before[f"{name}.wav"][44:] for name in ("triangle", "curve", "circuit"))
    committed = {p.name: digest(p) for p in output.iterdir()}
    native["calls"].clear()
    checked = await education.check_lesson(output, result["receipt"]["sha256"])
    assert checked["status"] == "verified"
    assert len([c for c in native["calls"] if Path(c[0]).name == "ffprobe"]) == 1
    assert {p.name: digest(p) for p in output.iterdir()} == committed
    assert all((tmp_path / name).read_bytes() == body for name, body in before.items())
    assert not list(tmp_path.glob(".education-check-*"))


def defective_source(defect, data, parent):
    """Keep schema/path mutations separate from complete WAV-body mutations."""
    segment = parent / "curve.wav"
    if defect in {"missing", "reordered", "duplicate"}:
        if defect == "missing":
            data["narration_segments"].pop()
        elif defect == "reordered":
            data["narration_segments"].reverse()
        else:
            data["narration_segments"][1] = data["narration_segments"][0]
    elif defect == "hash":
        data["narration_segments"][1]["sha256"] = "a" * 64
    elif defect in {"uri", "traversal", "symlink", "fifo"}:
        if defect == "uri":
            data["narration_segments"][1]["path"] = "https://example.com/audio.wav"
        elif defect == "traversal":
            data["narration_segments"][1]["path"] = "../curve.wav"
        else:
            segment.unlink()
            if defect == "symlink":
                segment.symlink_to(parent / "triangle.wav")
            else:
                import os
                os.mkfifo(segment)
    elif defect == "declared":
        data["storyboard"]["scenes"][0]["end_seconds"] = 2
    else:
        data["schema_version"] = True


def defective_wav(defect, data, segment):
    """Mutate independently committed RIFF data/format bytes for admission controls."""
    body = segment.read_bytes()
    if defect == "changed":
        body = body[:-2] + b"\x00\x00"
    elif defect == "truncated":
        body = body[:-1]
    elif defect == "extra_bytes":
        body += b"hidden"
    elif defect == "odd_samples":
        body = body[:-1]
        body = body[:4] + struct.pack("<I", len(body) - 8) + body[8:40] + struct.pack("<I", len(body) - 44) + body[44:]
    elif defect == "rate":
        body = body[:24] + struct.pack("<I", 44100) + body[28:]
    elif defect == "stereo":
        body = body[:22] + struct.pack("<H", 2) + body[24:]
    else:
        body = wav_bytes(0)
    segment.write_bytes(body)
    if defect != "changed":
        data["narration_segments"][1]["sha256"] = digest(segment)


@pytest.mark.parametrize("defect", ["missing", "reordered", "duplicate", "hash", "changed", "truncated", "extra_bytes", "odd_samples", "rate", "stereo", "empty", "total", "invisible", "uri", "traversal", "symlink", "fifo", "declared", "bool_version"])
async def test_measured_segment_admission_refuses_invalid_population_before_native(defect, tmp_path, clean_config, native):
    """GIVEN malformed scene/audio commitments WHEN admitted THEN no output/native work starts."""
    counts = (4501, 7003, 5009)
    if defect == "total":
        counts = (480001, 480000, 480000)
    elif defect == "invisible":
        counts = (1, 1, 8000)
    inputs = measured_inputs(tmp_path, counts)
    data = json.loads(Path(inputs["spec_path"]).read_bytes())
    if defect in {"changed", "truncated", "extra_bytes", "odd_samples", "rate", "stereo", "empty"}:
        defective_wav(defect, data, tmp_path / "curve.wav")
    elif defect not in {"total", "invisible"}:
        defective_source(defect, data, tmp_path)
    path = Path(inputs["spec_path"])
    path.write_bytes(json.dumps(data).encode())
    inputs["expected_spec_sha256"] = digest(path)
    with pytest.raises((ValueError, PermissionError, FileNotFoundError, ValidationError)):
        await education.build_lesson(**inputs)
    assert native["calls"] == [] and not Path(inputs["output_directory"]).exists()
    assert len(list(tmp_path.glob(".education-attempt-*.json"))) == 1


async def test_schema2_refuses_ambiguous_legacy_audio_arguments(tmp_path, clean_config, native):
    inputs = measured_inputs(tmp_path)
    with pytest.raises(ValueError, match="omit legacy"):
        await education.validate_lesson(inputs["spec_path"], inputs["expected_spec_sha256"], str(tmp_path / "triangle.wav"), digest(tmp_path / "triangle.wav"))
    assert native["calls"] == []


def test_sample_frame_quantization_has_explicit_oracles_and_no_audio_adjustment():
    timeline = timeline_from_counts([4000, 4001, 4000])
    assert timeline["total_samples"] == 12001 and timeline["frame_count"] == 4
    assert list(frame_schedule(timeline)) == [(0, 0), (1, 1), (2, 1), (3, 2)]
    assert timeline["scenes"][2]["visual_delay_samples"] == 3999
    assert timeline["video_tail_samples"] == 3999
    timeline = timeline_from_counts([480000, 480000, 480000])
    assert timeline["frame_count"] == 360 and timeline["video_tail_samples"] == 0
    with pytest.raises(ValueError, match="total"):
        timeline_from_counts([480000, 480000, 480001])


def test_legacy_page_bytes_match_pinned_schema1_caller_artifact():
    """Preserve the exact page bytes independently measured at the assignment's pinned HEAD."""
    from video_research_mcp.models.education import LessonSpec
    page = education.page_bytes(LessonSpec.model_validate(spec_fixture()), b"legacy-page-byte-contract-only")
    assert hashlib.sha256(page).hexdigest() == "8c764d022e7103f1db673604cbb244e3c77fc9c24dd5677512c6746f0b19d82e"


def test_measured_page_sample_seek_scene_reset_audio_clock_contract(tmp_path):
    inputs = measured_inputs(tmp_path)
    admitted = education_audio.admit(inputs["spec_path"], inputs["expected_spec_sha256"], None, None, threading.Event(), time.monotonic() + 10)
    spec, _, body, audio, _, _, _ = admitted
    page = education.page_bytes(spec, body, timeline=audio["timeline"]).decode()
    payload = json.loads(page.split('<script id="lesson-data" type="application/json">')[1].split('</script>')[0])
    assert payload["timeline"] == audio["timeline"]
    assert payload["spec"]["script"]["transcript"] == spec.script.transcript
    assert 'max="16513" step="1"' in page
    assert "seek(clock.scenes[Number(b.dataset.scene)].start_sample)" in page
    assert "state.sample<s.end_sample" in page
    assert "setSample(audio.currentTime*clock.sample_rate);draw()" in page
    assert "state.seconds=state.sample/clock.sample_rate" in page
    assert "state.reflection=true;state.shift=0;seek(0)" in page
    assert "Math.min(6" not in page and "Math.floor(state.seconds/2)" not in page


def test_measured_browser_microsecond_clock_preserves_scene_boundary_samples():
    """GIVEN browser-rounded media seconds WHEN the shipped JS updates THEN exact scene samples survive."""
    from video_research_mcp.education_page import MEASURED_SCRIPT
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to execute the page JavaScript regression")
    setter = re.search(r"function setSample\(sample\)\{[^}]+\}", MEASURED_SCRIPT).group()
    script = "const clock={sample_rate:48000,total_samples:1440000},state={};" + setter
    script += "const points=[];for(const n of [0,48625,200946,374159,480000,960000,1440000]){for(const seconds of [(n/48000).toFixed(6),Math.floor(n/48000*1e6)/1e6]){setSample(Number(seconds)*48000);points.push(state.sample);}}console.log(JSON.stringify(points));"
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True, timeout=10)
    assert json.loads(result.stdout) == [n for n in (0, 48625, 200946, 374159, 480000, 960000, 1440000) for _ in range(2)]


def test_measured_authored_gate_rejects_extra_png_and_changed_clock(tmp_path):
    inputs = measured_inputs(tmp_path)
    spec = MeasuredLessonSpec.model_validate(json.loads(Path(inputs["spec_path"]).read_bytes()))
    timeline = timeline_from_counts([4501, 7003, 5009])
    cancel, deadline = threading.Event(), time.monotonic() + 10
    frames = authored_frames(spec, tmp_path, cancel, deadline, timeline=timeline)
    authored_gate(spec, tmp_path, frames, cancel, deadline, timeline=timeline)
    changed = copy.deepcopy(frames)
    changed[2]["timeline_sample"] += 1
    with pytest.raises(ValueError, match="sample clock"):
        authored_gate(spec, tmp_path, changed, cancel, deadline, timeline=timeline)
    extra = tmp_path / "frame-005.png"
    extra.write_bytes((tmp_path / "frame-004.png").read_bytes())
    with pytest.raises(ValueError, match="extra/missing"):
        authored_gate(spec, tmp_path, frames, cancel, deadline, timeline=timeline)


def test_riff_admission_keeps_metadata_bytes_and_exact_data_with_odd_padded_chunks(tmp_path):
    body = wav_bytes(4501)
    body = body[:36] + b"JUNK" + struct.pack("<I", 3) + b"abc\x00" + body[36:]
    body = body[:4] + struct.pack("<I", len(body) - 8) + body[8:]
    riff_gate(body, expected_samples=None)
    pcm, measured = education_audio.measure_wav(body, "input.wav")
    assert measured["sha256"] == hashlib.sha256(body).hexdigest()
    assert pcm == b"\x00\x04" * 4501
    with pytest.raises(ValueError):
        riff_gate(body)


@pytest.mark.parametrize("action", ["cancel", "timeout", "lock_timeout"])
async def test_measured_deadline_cancel_join_cleanup_and_failed_receipt(action, tmp_path, clean_config, native):
    inputs = measured_inputs(tmp_path)
    native["block"] = True
    if action == "lock_timeout":
        async with education._LOCK:
            with pytest.raises(TimeoutError):
                await education.build_lesson(**inputs, timeout_seconds=.03)
        assert native["calls"] == []
    else:
        task = asyncio.create_task(education.build_lesson(**inputs, timeout_seconds=1 if action == "timeout" else 10))
        await native["entered"].wait()
        if action == "cancel":
            task.cancel()
        with pytest.raises(asyncio.CancelledError if action == "cancel" else TimeoutError):
            await task
    assert native["joined"] and not Path(inputs["output_directory"]).exists()
    attempts = list(tmp_path.glob(".education-attempt-*.json"))
    assert len(attempts) == 1
    assert json.loads(attempts[0].read_bytes())["status"] == ("cancelled" if action == "cancel" else "failed")
    assert not [p for p in tmp_path.glob(".education-*") if p.is_dir()]
    assert all((tmp_path / f"{name}.wav").exists() for name in ("triangle", "curve", "circuit"))
