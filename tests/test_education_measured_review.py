"""Measured-route output, restart and public CLI controls; native transport stays mocked."""

import asyncio
import copy
import hashlib
import json
import runpy
import threading
import time
from pathlib import Path

import pytest

from tests.test_education_timing import measured_inputs
from tests.test_education_workflow import digest, native, probe_reply
from video_research_mcp import education, education_review
from video_research_mcp.education_native import inspect_video, mux_command
from video_research_mcp.education_timing import timeline_from_counts
from video_research_mcp.footage_edit_native import NativeWork

__all__ = ["native"]
CLI = Path(__file__).resolve().parents[1] / "skills/educational-explainer/scripts/lesson.py"


async def test_full30_seconds360_frames_build_and_restart_have_complete_bounded_evidence(tmp_path, clean_config, native):
    """GIVEN thirty seconds with fractional scene boundaries THEN all360 frames and PCM rejoin."""
    inputs = measured_inputs(tmp_path, (480001, 479998, 480001))
    result = await education.build_lesson(**inputs)
    output = Path(result["directory"])
    receipt = json.loads((output / "receipt.json").read_bytes())
    assert len(receipt["frames"]) == 360
    assert [len([f for f in receipt["frames"] if f["scene_id"] == scene]) for scene in ("triangle", "curve", "circuit")] == [121, 119, 120]
    assert receipt["audio"]["frames"] == 1440000
    assert receipt["finished_output"]["decoded_rgb"]["bytes"] == 248832000
    assert receipt["finished_output"]["authored_source_output"]["inspected_frames"] == 360
    assert len(receipt["finished_output"]["technical"]["decoded_frames"]) == 360
    assert (output / "decoded.rgb").stat().st_size == 248832000
    assert 131072 < result["receipt"]["bytes"] <= 524288
    assert (output / "video.mp4").stat().st_size <= 8388608
    probe_calls = [c for c in native["calls"] if Path(c[0]).name == "ffprobe"]
    assert len(probe_calls) == 1
    raw = next(c for c in native["calls"] if "rawvideo" in c)
    assert "-frames:v" not in raw
    assert raw[raw.index("-fs") + 1] == "268435456"
    checked = await education.check_lesson(output, result["receipt"]["sha256"])
    assert checked["finished_output"]["audio_pcm"]["pcm_sha256"] == receipt["audio"]["pcm_sha256"]
    assert checked["unverified"]["speech_semantics_verified"] is False


@pytest.mark.parametrize("mutation", ["original_segment", "original_source", "segment_commitment", "sample_commitment", "timeline", "staged_segment", "assembled_pcm", "self_receipt", "extra_png", "missing_png", "receipt_population", "decoded_population"])
async def test_measured_restart_rejects_original_segment_clock_and_artifact_mutations(mutation, tmp_path, clean_config, native):
    """GIVEN committed output WHEN originals or evidence drift THEN checking refuses delivery."""
    inputs = measured_inputs(tmp_path)
    built = await education.build_lesson(**inputs)
    directory = Path(built["directory"])
    receipt_path = directory / "receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    expected = built["receipt"]["sha256"]
    if mutation == "original_segment":
        (tmp_path / "curve.wav").write_bytes((tmp_path / "curve.wav").read_bytes()[:-2] + b"xx")
    elif mutation == "original_source":
        Path(inputs["spec_path"]).write_bytes(Path(inputs["spec_path"]).read_bytes() + b" ")
    elif mutation == "segment_commitment":
        receipt["originals"]["segment_curve"]["sha256"] = "a" * 64
    elif mutation == "sample_commitment":
        receipt["audio"]["segments"][1]["pcm_sha256"] = "b" * 64
    elif mutation == "timeline":
        receipt["audio"]["timeline"]["scenes"][1]["start_sample"] -= 1
    elif mutation == "staged_segment":
        (directory / "segment-curve.wav").write_bytes((directory / "segment-curve.wav").read_bytes() + b"edited")
    elif mutation == "assembled_pcm":
        (directory / "narration.wav").write_bytes((directory / "narration.wav").read_bytes()[:-2] + b"xx")
    elif mutation == "self_receipt":
        receipt["status"] = "complete-but-edited"
    elif mutation == "extra_png":
        (directory / "frame-005.png").write_bytes((directory / "frame-004.png").read_bytes())
    elif mutation == "missing_png":
        (directory / "frame-004.png").unlink()
    elif mutation == "receipt_population":
        receipt["files"].pop()
    else:
        with (directory / "decoded.rgb").open("ab") as writer:
            writer.write(b"extra frame body")
    if mutation in {"segment_commitment", "sample_commitment", "timeline", "self_receipt", "receipt_population"}:
        receipt_path.write_bytes(json.dumps(receipt).encode())
        if mutation != "self_receipt":
            expected = digest(receipt_path)
    native["calls"].clear()
    with pytest.raises((ValueError, FileNotFoundError)):
        await education.check_lesson(directory, expected)
    assert native["calls"] == []
    assert not list(tmp_path.glob(".education-check-*"))


@pytest.mark.parametrize("mutation", ["original_segment", "decoded_sample", "extra_raw", "missing_raw"])
async def test_measured_build_refuses_mutation_and_keeps_bounded_failed_attempt(mutation, tmp_path, clean_config, native):
    inputs = measured_inputs(tmp_path)
    changed = False
    def mutate(command):
        nonlocal changed
        if changed:
            return
        if mutation == "original_segment" and "libx264rgb" in command:
            path = tmp_path / "triangle.wav"
        elif mutation == "decoded_sample" and "pcm_s16le" in command:
            path = Path(command[-1])
        elif mutation in {"extra_raw", "missing_raw"} and "rawvideo" in command:
            path = Path(command[-1])
        else:
            return
        if mutation == "extra_raw":
            with path.open("ab") as writer:
                writer.write(b"\x00" * 691200)
        elif mutation == "missing_raw":
            with path.open("r+b") as writer:
                writer.truncate(path.stat().st_size - 691200)
        else:
            with path.open("r+b") as writer:
                writer.seek(44)
                writer.write(b"\x7f\x7f")
        changed = True
    native["hook"] = mutate
    with pytest.raises(ValueError):
        await education.build_lesson(**inputs)
    assert changed and not Path(inputs["output_directory"]).exists()
    attempts = list(tmp_path.glob(".education-attempt-*.json"))
    assert len(attempts) == 1 and attempts[0].stat().st_size < 4096
    assert not [p for p in tmp_path.glob(".education-*") if p.is_dir()]


@pytest.mark.parametrize("defect", ["extra_frame", "missing_frame", "video_pts", "video_time", "audio_gap", "audio_overlap", "audio_samples", "extra_stream", "hidden_frame", "container_end", "audio_end"])
async def test_measured_full_probe_clock_population_has_no_truncation_or_gaps(defect, native, tmp_path):
    """GIVEN the complete probe JSON WHEN a single clock/count changes THEN exact clocks refuse."""
    timeline = timeline_from_counts([148001, 111007, 96001])
    info = probe_reply(89, 355009)
    rows = info["frames"]
    if defect == "extra_frame":
        rows.insert(89, {"stream_index": 0, "pts": 89000, "pts_time": str(89 / 12)})
    elif defect == "missing_frame":
        rows.pop(88)
    elif defect == "video_pts":
        rows[35]["pts"] += 1
    elif defect == "video_time":
        rows[35]["pts_time"] = "NaN"
    elif defect in {"audio_gap", "audio_overlap"}:
        rows[90]["pts"] += 1 if defect == "audio_gap" else -1
    elif defect == "audio_samples":
        rows[89]["nb_samples"] = True
    elif defect == "extra_stream":
        info["streams"].append({"index": 2, "codec_type": "subtitle"})
    elif defect == "hidden_frame":
        rows.append({"stream_index": 2, "pts": 0})
    elif defect == "container_end":
        info["format"]["duration"] = "7.3"
    else:
        rows[-1]["nb_samples"] -= 1
    async def run(*_):
        return json.dumps(info).encode(), b""
    work = NativeWork(time.monotonic() + 120)
    work.run = run
    with pytest.raises(ValueError):
        result = await inspect_video(tmp_path / "fake.mp4", work)
        education_review.clock_gate(result, timeline)


def test_fractional_output_end_is_video_quantized_without_audio_padding():
    timeline = timeline_from_counts([148001, 111007, 96001])
    measured = {"output": {"frame_count": 89, "decoded_frame_seconds": [n / 12 for n in range(89)],
                          "duration_seconds": 7.417, "width": 640, "height": 360, "video_codec": "h264"},
                "audio": {"sample_count": 355009, "sample_rate": 48000, "duration_seconds": 355009 / 48000,
                          "first_seconds": 0, "end_seconds": 355009 / 48000}}
    education_review.clock_gate(measured, timeline)
    wrong = copy.deepcopy(measured)
    wrong["audio"].update(sample_count=356000, duration_seconds=356000 / 48000, end_seconds=356000 / 48000)
    with pytest.raises(ValueError, match="sample population"):
        education_review.clock_gate(wrong, timeline)


async def test_measured_cli_validate_build_and_check_route(tmp_path, clean_config, native):
    inputs = measured_inputs(tmp_path)
    cli = runpy.run_path(str(CLI))
    common = ["--spec", inputs["spec_path"], "--spec-sha256", inputs["expected_spec_sha256"]]
    admitted = await cli["run"](cli["parser"]().parse_args(["validate", *common]))
    assert admitted["audio"]["frames"] == 16513 and native["calls"] == []
    built = await cli["run"](cli["parser"]().parse_args(["build", *common, "--output", inputs["output_directory"]]))
    checked = await cli["run"](cli["parser"]().parse_args(["check", built["directory"], "--receipt-sha256", built["receipt"]["sha256"]]))
    assert checked["status"] == "verified"


def test_measured_cli_main_exposes_validation_and_nonzero_refusal(tmp_path, clean_config, native, monkeypatch, capsys):
    inputs = measured_inputs(tmp_path)
    cli = runpy.run_path(str(CLI))
    monkeypatch.setattr("sys.argv", [str(CLI), "validate", "--spec", inputs["spec_path"], "--spec-sha256", inputs["expected_spec_sha256"]])
    assert cli["main"]() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "validated"
    Path(inputs["spec_path"]).write_bytes(b"changed")
    assert cli["main"]() == 1
    assert json.loads(capsys.readouterr().out)["error_type"] == "ValueError"
    assert native["calls"] == []


async def test_measured_worker_cancellation_joins_before_cleanup(tmp_path, clean_config, native, monkeypatch):
    """GIVEN a running admission thread WHEN cancelled THEN it joins before return."""
    inputs = measured_inputs(tmp_path)
    entered, joined = threading.Event(), threading.Event()
    def blocked(*args):
        cancelled = args[-2]
        entered.set()
        while not cancelled.wait(.01):
            pass
        joined.set()
        raise TimeoutError("controlled cooperative worker cancellation")
    monkeypatch.setattr(education, "_admit", blocked)
    task = asyncio.create_task(education.build_lesson(**inputs))
    while not entered.is_set():
        await asyncio.sleep(.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert joined.is_set() and native["calls"] == []
    assert not Path(inputs["output_directory"]).exists()
    assert len(list(tmp_path.glob(".education-attempt-*.json"))) == 1


def test_measured_mux_preserves_full_pcm_and_has_no_fit_to_grid_transform(native, tmp_path):
    command = mux_command(tmp_path, 89)
    assert command[command.index("-frames:v") + 1] == "89"
    assert command[command.index("-c:a") + 1] == "alac"
    assert "-shortest" not in command and "-t" not in command
    assert "-ar" not in command and "-ac" not in command and "-af" not in command
    assert "-y" not in command and "-n" in command


@pytest.mark.parametrize("version,limit", [(1, 131072), (2, 524288)])
async def test_restart_receipt_byte_bounds_refuse_before_any_native(version, limit, tmp_path, clean_config, native):
    """Keep the128KiB legacy ceiling when the measured receipt reader admits up to512KiB."""
    directory = tmp_path / "receipt-output"
    directory.mkdir()
    body = json.dumps({"schema_version": version, "status": "complete"}).encode()
    body += b" " * (limit + 1 - len(body))
    (directory / "receipt.json").write_bytes(body)
    with pytest.raises(ValueError, match="receipt|byte ceiling"):
        await education.check_lesson(directory, hashlib.sha256(body).hexdigest())
    assert native["calls"] == [] and not list(tmp_path.glob(".education-check-*"))
