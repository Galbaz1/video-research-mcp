"""Validate, produce and restart-check one bounded first-party educational page/video lesson."""

import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import time
import uuid

from .audio_dsp_pcm import read_pcm
from .education_domain import source_gate
from .education_frames import authored_frames
from .education_native import NativeWork, mux_command
from .education_page import page_bytes
from .education_review import (file_record, finished_gate, read_bytes, rejoin_files, riff_gate,
                               safe_path, strict_json)
from .image_preprocessing import image_worker
from .models.education import LessonSpec

_LOCK = asyncio.Lock()
UNEXECUTED = ["Problem Display Card", "Formula Derivation Panel", "Geometry Canvas", "Step Indicator",
              "Conclusion Panel", "Flame Color Display", "Title Opening", "Experiment Equipment Cards",
              "Operation Flow Panel", "Comparison Panel", "Science Principle Diagram", "Circuit Wiring Operation Panel"]


def _deadline(seconds):
    """Keep one finite caller deadline, including waiting for serialized native work."""
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 120:
        raise ValueError("Lesson timeout must be finite and positive, at most120 seconds")
    return time.monotonic() + seconds


def _digest(body, expected):
    """Require an independent complete byte commitment, not an editable self-receipt."""
    if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("Lesson requires an explicit full expected SHA256")
    if hashlib.sha256(body).hexdigest() != expected:
        raise ValueError("Lesson exact expected SHA256 differs from actual bytes")


def _admit(spec_path, spec_sha, audio_path, audio_sha, cancelled, deadline):
    """Validate complete actual source/audio before any native work or output allocation."""
    spec_path, audio_path = safe_path(spec_path), safe_path(audio_path)
    source = read_bytes(spec_path, 131072, cancelled, deadline)
    audio = read_bytes(audio_path, 8388608, cancelled, deadline)
    _digest(source, spec_sha)
    _digest(audio, audio_sha)
    spec = LessonSpec.model_validate(strict_json(source))
    riff_gate(audio)
    _, measured = read_pcm(audio_path, 1, cancelled, deadline)
    if measured["sha256"] != audio_sha:
        raise ValueError("Narration bytes changed during measured PCM admission")
    report = source_gate(spec, measured)
    originals = {"spec": {"path": str(spec_path), "sha256": spec_sha, "bytes": len(source)},
                 "audio": {"path": str(audio_path), "sha256": audio_sha, "bytes": len(audio)}}
    return spec, source, audio, measured, report, originals


async def _admission(spec_path, spec_sha, audio_path, audio_sha, deadline):
    return await image_worker(_admit, spec_path, spec_sha, audio_path, audio_sha, deadline=deadline)


def _write(path, body):
    """Create an exclusive owned artifact with fsync; never overwrite prior output."""
    with safe_path(path).open("xb") as writer:
        os.fchmod(writer.fileno(), 0o600)
        writer.write(body)
        writer.flush()
        os.fsync(writer.fileno())


async def _originals(records, deadline):
    for record in records.values():
        body = await image_worker(read_bytes, record["path"], record["bytes"], deadline=deadline)
        _digest(body, record["sha256"])


def _unverified():
    """Do not promote a finite lesson component into voice, physics or template acceptance."""
    return {"speech_semantics_verified": False, "caption_speech_alignment_verified": False,
            "multilingual_glyph_acceptance": "unqualified; unsupported glyphs refused",
            "arbitrary_math_physics": "unqualified", "browser_interactions": "unverified",
            "human_lesson_acceptance": "unverified", "whole_native_certificate": "partial ordinary host; no OS sandbox",
            "foreign_runtime_closure": "INCOMPLETE:39 direct unread bodies; no foreign execution",
            "upstream_component_templates": {name: "UNEXECUTED_UNQUALIFIED" for name in UNEXECUTED},
            "external_workflows": ["HyperFrames renderer", "GSAP/KaTeX/font assets", "provider narration",
                                   "multilingual teaching", "arbitrary scientific process animations"]}


async def validate_lesson(spec_path, expected_spec_sha256, audio_path, expected_audio_sha256, timeout_seconds=120):
    """Read exact regular inputs and admit every applicable source domain without native execution."""
    deadline = _deadline(timeout_seconds)
    async with asyncio.timeout(timeout_seconds):
        _, _, _, audio, report, originals = await _admission(spec_path, expected_spec_sha256, audio_path, expected_audio_sha256, deadline)
        await _originals(originals, deadline)
    return {"status": "validated", "source_domain": report, "originals": originals,
            "audio": audio, "unverified": _unverified(), "native_executed": False}


async def _prepare(spec, source, audio, directory, deadline):
    _write(directory / "source.json", source)
    _write(directory / "narration.wav", audio)
    _write(directory / "page.html", page_bytes(spec, audio))
    frames = await image_worker(authored_frames, spec, directory, deadline=deadline)
    if sum(f["bytes"] for f in frames) > 8388608:
        raise ValueError("Authored lesson PNG population exceeds8MiB")
    records = [await image_worker(file_record, directory / name, directory, maximum, deadline=deadline)
               for name, maximum in [("source.json", 131072), ("narration.wav", 8388608), ("page.html", 8388608)]]
    records.extend({k: f[k] for k in ("path", "sha256", "bytes")} for f in frames)
    return frames, records


def _promote(stage, output, receipt_body):
    """Claim an absent destination atomically and link exclusive files without overwriting."""
    _write(stage / "receipt.json", receipt_body)
    safe_path(output).mkdir(mode=0o700)
    linked = []
    try:
        for source in stage.iterdir():
            target = output / source.name
            os.link(source, target, follow_symlinks=False)
            linked.append(target)
    except BaseException:
        for target in linked:
            target.unlink()
        if not any(output.iterdir()):
            output.rmdir()
        raise
    return linked


def _discard_promoted(linked, stage, output):
    """Remove only this invocation's hardlinks if the final joined readback fails."""
    for path in linked:
        original = (stage / path.name).lstat()
        if path.exists() and (path.lstat().st_dev, path.lstat().st_ino) == (original.st_dev, original.st_ino):
            path.unlink()
    if linked and output.exists() and not any(output.iterdir()):
        output.rmdir()


def _failed_attempt(exc, attempt, stage, output, linked):
    """Retain a bounded failure receipt after removing only invocation-created outputs."""
    _discard_promoted(linked, stage, output)
    attempt.update(status="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed", error_type=type(exc).__name__)
    record = output.parent / (".education-attempt-" + stage.name.removeprefix(".education-") + ".json")
    _write(record, (json.dumps(attempt, indent=2) + "\n").encode())
    exc.lesson_attempt_path = str(record)


async def _build(admitted, directory, work, attempt):
    spec, source, audio_body, audio, source_report, originals = admitted
    frames, files = await _prepare(spec, source, audio_body, directory, work.deadline)
    attempt["stages"].append({"stage": "authored_page_frames", "status": "passed"})
    await _originals(originals, work.deadline)
    await image_worker(rejoin_files, directory, files, deadline=work.deadline)
    await work.admit()
    await work.run(mux_command(directory))
    files.append(await image_worker(file_record, directory / "video.mp4", directory, 8388608, deadline=work.deadline))
    attempt["stages"].append({"stage": "encoded_identity_bound_before_QA", "status": "passed", "video": files[-1]})
    review = await finished_gate(spec, directory, frames, files, audio, work, directory)
    files.extend(review["evidence"])
    await _originals(originals, work.deadline)
    await image_worker(rejoin_files, directory, files, deadline=work.deadline)
    await work.verify()
    attempt["stages"].append({"stage": "finished_output_and_original_rejoin", "status": "passed"})
    return {"schema_version": 1, "status": "complete", "lesson": spec.title, "originals": originals,
            "source_domain": source_report, "audio": {**audio, "path": "narration.wav"}, "frames": frames,
            "files": files, "finished_output": review, "native_identities": work.identities,
            "attempt": {**attempt, "status": "complete"}, "unverified": _unverified()}


async def build_lesson(spec_path, expected_spec_sha256, audio_path, expected_audio_sha256, output_directory, timeout_seconds=120):
    """Produce a complete finite lesson into an absent directory, preserving durable failed attempts."""
    deadline, output = _deadline(timeout_seconds), safe_path(output_directory)
    if output.exists() or not output.parent.is_dir():
        raise FileExistsError("Lesson output must be absent with an existing regular parent directory")
    stage = output.parent / (".education-" + uuid.uuid4().hex)
    attempt, linked, created = {"status": "running", "stages": [], "output_directory": str(output)}, [], False
    try:
        async with asyncio.timeout(timeout_seconds), _LOCK:
            admitted = await _admission(spec_path, expected_spec_sha256, audio_path, expected_audio_sha256, deadline)
            attempt["stages"].append({"stage": "source_domain_audio_admitted", "status": "passed"})
            stage.mkdir(mode=0o700)
            created = True
            receipt = await _build(admitted, stage, NativeWork(deadline), attempt)
            body = (json.dumps(receipt, indent=2, allow_nan=False) + "\n").encode()
            if len(body) > 131072:
                raise ValueError("Lesson receipt exceeds128KiB")
            linked = _promote(stage, output, body)
            await image_worker(rejoin_files, output, receipt["files"], deadline=deadline)
            await _originals(receipt["originals"], deadline)
            _digest(await image_worker(read_bytes, output / "receipt.json", 131072, deadline=deadline), hashlib.sha256(body).hexdigest())
        return {"status": "complete", "directory": str(output), "receipt": {"path": str(output / "receipt.json"),
                "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)},
                "page": next(r for r in receipt["files"] if r["path"] == "page.html"),
                "video": next(r for r in receipt["files"] if r["path"] == "video.mp4"),
                "source_domain": receipt["source_domain"], "finished_output": receipt["finished_output"], "unverified": receipt["unverified"]}
    except BaseException as exc:
        _failed_attempt(exc, attempt, stage, output, linked)
        raise
    finally:
        if created:
            shutil.rmtree(stage)


async def _check(directory, expected_sha, work, scratch):
    body = await image_worker(read_bytes, directory / "receipt.json", 131072, deadline=work.deadline)
    _digest(body, expected_sha)
    receipt = strict_json(body)
    if receipt.get("schema_version") != 1 or receipt.get("status") != "complete":
        raise ValueError("Lesson receipt is incomplete; failed/skipped source gates cannot pass restart")
    required = {"source.json", "narration.wav", "page.html", "video.mp4", "decoded.rgb", "decoded.wav"}
    required.update(f"frame-{n:03}.png" for n in range(72))
    if {r["path"] for r in receipt["files"]} != required:
        raise ValueError("Lesson receipt omits or adds a required complete artifact population")
    await image_worker(rejoin_files, directory, receipt["files"], deadline=work.deadline)
    original = receipt["originals"]
    admitted = await _admission(original["spec"]["path"], original["spec"]["sha256"], original["audio"]["path"], original["audio"]["sha256"], work.deadline)
    spec, source, audio_body, audio, report, originals = admitted
    if originals != original or report != receipt["source_domain"]:
        raise ValueError("Lesson source-domain commitments changed or applicable checks were omitted")
    if page_bytes(spec, audio_body) != await image_worker(read_bytes, directory / "page.html", 8388608, deadline=work.deadline):
        raise ValueError("Lesson page is not the actual source-derived self-contained page")
    for name, expected in [("source.json", source), ("narration.wav", audio_body)]:
        if await image_worker(read_bytes, directory / name, 8388608, deadline=work.deadline) != expected:
            raise ValueError("Lesson staged source/audio differs from exact original bytes")
    await work.admit()
    if work.identities != receipt["native_identities"]:
        raise ValueError("Installed lesson native identities changed since the committed QA")
    review = await finished_gate(spec, directory, receipt["frames"], receipt["files"], audio, work, scratch)
    if review["evidence"] != receipt["finished_output"]["evidence"]:
        raise ValueError("Restart decoded evidence differs from the committed complete output")
    await _originals(original, work.deadline)
    await image_worker(rejoin_files, directory, receipt["files"], deadline=work.deadline)
    _digest(await image_worker(read_bytes, directory / "receipt.json", 131072, deadline=work.deadline), expected_sha)
    await work.verify()
    return {"status": "verified", "directory": str(directory), "receipt_sha256": expected_sha,
            "source_domain": report, "finished_output": review, "unverified": _unverified()}


async def check_lesson(directory, expected_receipt_sha256, timeout_seconds=120):
    """Reopen external-hash-bound artifacts and repeat source plus complete native output checks."""
    deadline, directory = _deadline(timeout_seconds), safe_path(directory)
    scratch, created = directory.parent / (".education-check-" + uuid.uuid4().hex), False
    try:
        async with asyncio.timeout(timeout_seconds), _LOCK:
            scratch.mkdir(mode=0o700)
            created = True
            return await _check(directory, expected_receipt_sha256, NativeWork(deadline), scratch)
    finally:
        if created:
            shutil.rmtree(scratch)
