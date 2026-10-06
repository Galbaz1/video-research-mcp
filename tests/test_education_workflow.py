"""Real local file/worker/native identity lifecycle with only native execution mocked."""

import asyncio
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import wave

from PIL import Image
import pytest

from tests.test_education_domain import spec_fixture
from video_research_mcp import education
from video_research_mcp.education_native import mux_command


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wav_bytes(frames=288000):
    """Generate own deterministic PCM bytes; these are explicitly not spoken narration."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(48000)
        writer.writeframes(b"\x00\x04" * frames)
    return buffer.getvalue()


@pytest.fixture
def inputs(tmp_path, clean_config):
    source, audio = tmp_path / "lesson.json", tmp_path / "spoken-declared-but-unverified.wav"
    source.write_text(json.dumps(spec_fixture()))
    audio.write_bytes(wav_bytes())
    return {"spec_path": str(source), "expected_spec_sha256": digest(source), "audio_path": str(audio),
            "expected_audio_sha256": digest(audio), "output_directory": str(tmp_path / "result")}


def probe_reply(frames=72, samples=288000):
    video = {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 640, "height": 360, "time_base": "1/12000"}
    audio = {"index": 1, "codec_type": "audio", "codec_name": "alac", "sample_rate": "48000", "channels": 1, "time_base": "1/48000"}
    rows = [{"stream_index": 0, "pts": i * 1000, "pts_time": str(i / 12)} for i in range(frames)]
    rows.extend({"stream_index": 1, "pts": start, "pts_time": str(start / 48000),
                 "nb_samples": min(48000, samples - start)} for start in range(0, samples, 48000))
    return {"format": {"duration": str(math.ceil(frames / 12 * 1000) / 1000)}, "streams": [video, audio], "frames": rows}


def framehash_reply(directory, count=72):
    rows = ["#hash: SHA256", "#tb 0: 1/12"]
    for i in range(count):
        with Image.open(directory / f"frame-{i:03}.png") as image:
            sha = hashlib.sha256(image.tobytes()).hexdigest()
        rows.append(f"0, {i}, {i}, 1, 691200, {sha}")
    return ("\n".join(rows) + "\n").encode()


def native_reply(command):
    """Produce bounded fake transport evidence from the actual authored files."""
    directory = Path(command[command.index("-i") + 1]).parent
    count = len(list(directory.glob("frame-*.png")))
    with wave.open(str(directory / "narration.wav"), "rb") as reader:
        samples = reader.getnframes()
    if "libx264rgb" in command:
        Path(command[-1]).write_bytes(b"SYNTHETIC_MP4_BOUNDARY_ONLY_NO_NATIVE_ENCODING")
        return b"", b""
    if Path(command[0]).name == "ffprobe":
        return json.dumps(probe_reply(count, samples)).encode(), b""
    if "-progress" in command:
        return f"frame={count}\nprogress=end\n".encode(), b""
    if "ebur128=peak=true" in command:
        return b"", b" Summary:\n I: -20 LUFS\n LRA: 0 LU\n Peak: -12 dBFS\n"
    if "framehash" in command:
        return framehash_reply(directory, count), b""
    if "rawvideo" in command:
        with Path(command[-1]).open("xb") as writer:
            for i in range(count):
                with Image.open(directory / f"frame-{i:03}.png") as image:
                    writer.write(image.tobytes())
        return b"", b""
    if "pcm_s16le" in command:
        shutil.copyfile(directory / "narration.wav", command[-1])
        return b"", b""
    raise AssertionError(command)


@pytest.fixture
def native(monkeypatch, tmp_path):
    """Mock process transport; actual NativeWork hashes/rejoins owned fake executable files."""
    import video_research_mcp.education_native as owned_native
    import video_research_mcp.footage_edit_native as reused_native

    bins = tmp_path / "fake-binaries"
    bins.mkdir()
    for name in ("ffmpeg", "ffprobe"):
        (bins / name).write_bytes(b"unit-only-executable-placeholder")
    def resolve(name):
        return str(bins / name)
    monkeypatch.setattr(owned_native, "binary", resolve)
    monkeypatch.setattr(reused_native, "binary", resolve)
    state = {"calls": [], "hook": None, "joined": True, "entered": asyncio.Event(), "block": False}

    async def process(command, timeout):
        state["calls"].append(command)
        assert 0 < timeout <= 120
        assert "-protocol_whitelist" in command and "file" in command
        if "libx264rgb" in command:
            state["entered"].set()
            if state["block"]:
                state["joined"] = False
                try:
                    await asyncio.Future()
                finally:
                    state["joined"] = True
        result = native_reply(command)
        if state["hook"]:
            state["hook"](command)
        return result
    monkeypatch.setattr(reused_native, "run_media_process", process)
    return state


async def test_validate_has_no_native_or_output_side_effects(inputs, native):
    args = {k: v for k, v in inputs.items() if k != "output_directory"}
    result = await education.validate_lesson(**args)
    assert result["status"] == "validated" and result["native_executed"] is False
    assert result["audio"]["frames"] == 288000 and result["audio"]["sample_rate"] == 48000
    assert native["calls"] == [] and not Path(inputs["output_directory"]).exists()
    assert result["unverified"]["speech_semantics_verified"] is False


async def test_complete_build_and_restart_keep_real_file_commitments(inputs, native):
    result = await education.build_lesson(**inputs)
    directory = Path(result["directory"])
    assert result["receipt"]["sha256"] == digest(directory / "receipt.json")
    assert result["page"]["path"] == "page.html" and result["video"]["path"] == "video.mp4"
    receipt = json.loads((directory / "receipt.json").read_text())
    assert len(receipt["frames"]) == 72 and len(receipt["files"]) == 78
    assert (directory / "decoded.rgb").stat().st_size == 49766400
    assert receipt["finished_output"]["audio_pcm"]["frames"] == 288000
    before = {p.name: digest(p) for p in directory.iterdir()}
    checked = await education.check_lesson(directory, result["receipt"]["sha256"])
    assert checked["status"] == "verified" and checked["finished_output"]["decoded_rgb"]["rgb_tolerance"] == 0
    assert {p.name: digest(p) for p in directory.iterdir()} == before
    assert not list(directory.parent.glob(".education-check-*")) and not list(directory.parent.glob(".education-*[!.json]"))
    assert checked["unverified"]["speech_semantics_verified"] is False
    assert all(v == "UNEXECUTED_UNQUALIFIED" for v in checked["unverified"]["upstream_component_templates"].values())


@pytest.mark.parametrize("bad", ["source_sha", "audio_sha", "missing_audio", "truncated_audio", "sample_count", "existing_output", "symlink", "fifo", "traversal"])
async def test_input_refusals_precede_native_and_preserve_existing_files(bad, inputs, native):
    audio, source = Path(inputs["audio_path"]), Path(inputs["spec_path"])
    if bad == "source_sha":
        inputs["expected_spec_sha256"] = "a" * 64
    elif bad == "audio_sha":
        inputs["expected_audio_sha256"] = "a" * 64
    elif bad == "missing_audio":
        audio.unlink()
    elif bad == "truncated_audio":
        audio.write_bytes(audio.read_bytes()[:-2])
        inputs["expected_audio_sha256"] = digest(audio)
    elif bad == "sample_count":
        audio.write_bytes(wav_bytes(287999))
        inputs["expected_audio_sha256"] = digest(audio)
    elif bad == "existing_output":
        output = Path(inputs["output_directory"])
        output.mkdir()
        (output / "prior.txt").write_bytes(b"protected")
    elif bad == "symlink":
        link = source.parent / "link.json"
        link.symlink_to(source)
        inputs["spec_path"] = str(link)
    elif bad == "fifo":
        import os
        fifo = source.parent / "fifo.json"
        os.mkfifo(fifo)
        inputs["spec_path"] = str(fifo)
    else:
        inputs["spec_path"] = str(source.parent / ".." / source.parent.name / source.name)
    with pytest.raises((ValueError, PermissionError, FileNotFoundError, FileExistsError)):
        await education.build_lesson(**inputs)
    assert native["calls"] == []
    if bad == "existing_output":
        assert (Path(inputs["output_directory"]) / "prior.txt").read_bytes() == b"protected"


@pytest.mark.parametrize("drift", ["source", "audio", "page", "frame", "video", "binary"])
async def test_changed_original_staged_or_encoded_bytes_never_deliver(drift, inputs, native):
    changed = False
    def mutate(command):
        nonlocal changed
        if changed:
            return
        if (drift in {"source", "audio", "page", "frame", "binary"} and "libx264rgb" in command) or (drift == "video" and "-progress" in command):
            directory = Path(command[command.index("-i") + 1]).parent
            path = {"source": Path(inputs["spec_path"]), "audio": Path(inputs["audio_path"]), "page": directory / "page.html",
                    "frame": directory / "frame-000.png", "video": directory / "video.mp4", "binary": Path(command[0])}[drift]
            path.write_bytes(path.read_bytes() + b"changed")
            changed = True
    native["hook"] = mutate
    with pytest.raises(ValueError):
        await education.build_lesson(**inputs)
    assert not Path(inputs["output_directory"]).exists()
    assert not [p for p in Path(inputs["output_directory"]).parent.glob(".education-*") if p.is_dir()]
    attempts = list(Path(inputs["output_directory"]).parent.glob(".education-attempt-*.json"))
    assert len(attempts) == 1 and json.loads(attempts[0].read_text())["status"] == "failed"


async def test_cancellation_joins_mocked_native_then_removes_only_owned_stage(inputs, native):
    native["block"] = True
    task = asyncio.create_task(education.build_lesson(**inputs))
    await native["entered"].wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError) as caught:
        await task
    assert native["joined"] and not Path(inputs["output_directory"]).exists()
    receipt = Path(caught.value.lesson_attempt_path)
    assert json.loads(receipt.read_text())["status"] == "cancelled"
    assert not [p for p in receipt.parent.glob(".education-*") if p.is_dir()]


async def test_external_receipt_hash_blocks_rewritten_self_receipt_before_native(inputs, native):
    result = await education.build_lesson(**inputs)
    path = Path(result["receipt"]["path"])
    original = path.read_bytes()
    value = json.loads(original)
    value["source_domain"]["gates"]["curve"]["status"] = "skipped"
    path.write_text(json.dumps(value))
    native["calls"].clear()
    with pytest.raises(ValueError, match="SHA256"):
        await education.check_lesson(result["directory"], result["receipt"]["sha256"])
    assert native["calls"] == [] and path.read_bytes() != original


async def test_mutated_page_on_restart_cannot_accept_rewritten_artifact_hash(inputs, native):
    result = await education.build_lesson(**inputs)
    directory, receipt_path = Path(result["directory"]), Path(result["receipt"]["path"])
    page = directory / "page.html"
    page.write_bytes(page.read_bytes() + b"changed interactive equation")
    receipt = json.loads(receipt_path.read_text())
    record = next(r for r in receipt["files"] if r["path"] == "page.html")
    record.update(sha256=digest(page), bytes=page.stat().st_size)
    receipt_path.write_text(json.dumps(receipt))
    native["calls"].clear()
    with pytest.raises(ValueError, match="source-derived"):
        await education.check_lesson(directory, digest(receipt_path))
    assert native["calls"] == []


def test_mux_is_exact_file_only_lossless_and_has_no_resampling_or_overwrite(native, tmp_path):
    command = mux_command(tmp_path)
    assert command[command.index("-c:v") + 1] == "libx264rgb"
    assert command[command.index("-c:a") + 1] == "alac"
    assert command[command.index("-crf") + 1] == "0" and "-n" in command and "-y" not in command
    assert "-ar" not in command and "-ac" not in command and "volume" not in " ".join(command)
    assert command[command.index("-frames:v") + 1] == "72"


@pytest.mark.parametrize("seconds", [True, 0, -1, float("inf"), 121])
async def test_invalid_operation_deadlines_are_refused_before_any_work(seconds, inputs, native):
    with pytest.raises(ValueError):
        await education.build_lesson(**inputs, timeout_seconds=seconds)
    assert native["calls"] == []


async def test_post_promotion_original_change_discards_only_own_linked_outputs(inputs, native, monkeypatch):
    original = education._promote
    def promote(*args):
        linked = original(*args)
        source = Path(inputs["spec_path"])
        source.write_bytes(source.read_bytes() + b"changed")
        (Path(inputs["output_directory"]) / "unrelated.txt").write_bytes(b"preserve")
        return linked
    monkeypatch.setattr(education, "_promote", promote)
    with pytest.raises(ValueError):
        await education.build_lesson(**inputs)
    output = Path(inputs["output_directory"])
    assert [p.name for p in output.iterdir()] == ["unrelated.txt"]
    assert (output / "unrelated.txt").read_bytes() == b"preserve"


@pytest.mark.parametrize("substitute", [False, True])
async def test_post_promotion_receipt_drift_refuses_completion(inputs, native, monkeypatch, substitute):
    original = education._promote
    def promote(*args):
        linked = original(*args)
        path = Path(inputs["output_directory"]) / "receipt.json"
        changed = path.read_bytes() + b" "
        if substitute:
            path.unlink()
        path.write_bytes(changed)
        (path.parent / "unrelated.txt").write_bytes(b"preserve")
        return linked
    monkeypatch.setattr(education, "_promote", promote)
    with pytest.raises(ValueError, match="SHA256"):
        await education.build_lesson(**inputs)
    output = Path(inputs["output_directory"])
    assert (output / "unrelated.txt").read_bytes() == b"preserve"
    assert not (output / "video.mp4").exists()
    assert (output / "receipt.json").exists() is substitute
    attempts = list(output.parent.glob(".education-attempt-*.json"))
    assert len(attempts) == 1 and json.loads(attempts[0].read_text())["status"] == "failed"
