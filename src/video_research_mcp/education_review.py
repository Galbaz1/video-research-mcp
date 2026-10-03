"""Separate committed source checks, complete decoded-pixel/audio gates and restart readback."""

import hashlib
import json
import math
import os
from pathlib import Path
import struct
from functools import partial

from .audio_dsp_pcm import read_pcm
from .education_frames import expected_pixels, png_pixels
from .education_native import extract_evidence, inspect_video
from .education_timing import MAX_FRAMES, MAX_RGB_BYTES, RGB_BYTES, frame_schedule, legacy_timeline
from .footage_edit_qa import full_review
from .image_preprocessing import check_worker, image_worker
from .media_local_io import _copy_hash, _open_regular
from .media_snapshot import checked_path


def safe_path(value):
    """Refuse traversal as well as protocols/symlinks before the existing local fence."""
    if ".." in Path(value).parts:
        raise PermissionError("Lesson paths must not contain traversal")
    return checked_path(str(value))


def read_bytes(path, maximum, cancelled, deadline):
    """Read bounded regular bytes and reject file identity/content mutation during the read."""
    check_worker(cancelled, deadline)
    path = safe_path(path)
    with _open_regular(path) as reader:
        before = os.fstat(reader.fileno())
        if not 1 <= before.st_size <= maximum:
            raise ValueError("Lesson file is empty or exceeds its byte ceiling")
        body = reader.read(maximum + 1)
        after, current = os.fstat(reader.fileno()), path.lstat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if len(body) != before.st_size or any(getattr(before, k) != getattr(v, k) for k in fields for v in (after, current)):
        raise ValueError("Lesson file changed while reading")
    check_worker(cancelled, deadline)
    return body


def file_record(path, directory, maximum, cancelled, deadline):
    """Commit a complete regular file, including raw evidence too large for native stdout."""
    check_worker(cancelled, deadline)
    path = safe_path(path)
    digest, size = _copy_hash(path, cancelled=cancelled, max_bytes=maximum)
    check_worker(cancelled, deadline)
    return {"path": path.relative_to(directory).as_posix(), "sha256": digest, "bytes": size}


def strict_json(body):
    """Reject duplicate keys and nonfinite JSON instead of repairing a source/receipt."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Lesson JSON contains a duplicate key")
            result[key] = value
        return result
    def invalid(_):
        raise ValueError("Lesson JSON contains a nonfinite number")
    return json.loads(body, object_pairs_hook=pairs, parse_constant=invalid)


def riff_gate(body, expected_samples=288000):
    """Require one complete RIFF WAV with exact PCM16 format and complete data chunk."""
    if len(body) < 44 or body[:4] != b"RIFF" or body[8:12] != b"WAVE" or struct.unpack_from("<I", body, 4)[0] + 8 != len(body):
        raise ValueError("Narration must be a complete bounded RIFF WAV")
    offset, kinds = 12, []
    while offset < len(body):
        if offset + 8 > len(body):
            raise ValueError("Narration WAV chunk is truncated")
        kind, size = body[offset:offset + 4], struct.unpack_from("<I", body, offset + 4)[0]
        end = offset + 8 + size
        if end > len(body):
            raise ValueError("Narration WAV chunk body is truncated")
        kinds.append(kind)
        if kind == b"fmt " and (size < 16 or struct.unpack_from("<HHIIHH", body, offset + 8) != (1, 1, 48000, 96000, 2, 16)):
            raise ValueError("Narration WAV requires48kHz mono signed16 PCM")
        if kind == b"data":
            if size % 2 or not 2 <= size <= 2880000:
                raise ValueError("Narration WAV requires complete positive PCM samples through30 seconds")
            if expected_samples is not None and size != expected_samples * 2:
                raise ValueError(f"Narration WAV does not contain exactly{expected_samples} PCM samples")
        offset = end + (size % 2)
    if offset != len(body) or kinds.count(b"fmt ") != 1 or kinds.count(b"data") != 1:
        raise ValueError("Narration WAV has an ambiguous or incomplete chunk population")


def rejoin_files(directory, records, cancelled, deadline):
    """Reject missing/substituted artifacts using external receipt commitments."""
    names = [r["path"] for r in records]
    if len(set(names)) != len(names):
        raise ValueError("Lesson artifact commitments contain duplicate names")
    for record in records:
        name, size = record["path"], record["bytes"]
        if not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."}:
            raise PermissionError("Lesson artifact path escapes its owned directory")
        ceiling = MAX_RGB_BYTES if name == "decoded.rgb" else 8388608
        if type(size) is not int or not 1 <= size <= ceiling:
            raise ValueError("Lesson artifact byte commitment is invalid")
        actual = file_record(directory / name, directory, size, cancelled, deadline)
        if actual != record:
            raise ValueError("Lesson committed artifact bytes changed")


def authored_gate(spec, directory, frames, cancelled, deadline, *, timeline=None):
    """Reopen all PNGs and recompute source-derived shapes/glyphs instead of trusting hashes."""
    expected = expected_pixels(spec)
    timeline = legacy_timeline() if timeline is None else timeline
    count = timeline["frame_count"]
    if len(frames) != count:
        raise ValueError(f"Lesson is missing its complete{count}-frame population")
    if {p.name for p in directory.glob("frame-*.png")} != {f"frame-{n:03}.png" for n in range(count)}:
        raise ValueError("Lesson PNG population contains extra/missing frames")
    for frame, (index, scene_index) in zip(frames, frame_schedule(timeline), strict=True):
        check_worker(cancelled, deadline)
        if (frame["frame_index"], frame["scene_id"], frame["path"]) != (index, spec.storyboard.scenes[scene_index].id, f"frame-{index:03}.png"):
            raise ValueError("Lesson frame-to-scene population is inconsistent")
        if not math.isfinite(frame["timeline_seconds"]) or abs(frame["timeline_seconds"] - index / 12) > 1e-6 or frame["pixel_sha256"] != expected[scene_index]:
            raise ValueError("Lesson authored frame differs from the source clock/domain")
        if spec.schema_version == 2 and frame.get("timeline_sample") != index * 4000:
            raise ValueError("Lesson authored frame sample clock differs from the measured timeline")
        body = read_bytes(directory / frame["path"], 8388608, cancelled, deadline)
        if hashlib.sha256(body).hexdigest() != frame["sha256"] or len(body) != frame["bytes"] or png_pixels(body) != frame["pixel_sha256"]:
            raise ValueError("Lesson actual PNG pixels differ from committed source-derived frames")
    return {"status": "passed", "inspected_frames": count, "source_derived_scene_pixel_sha256": expected,
            "applicable_gates": ["geometry", "curve", "equation_glyphs", "circuit", "captions"], "all_skipped": False}


def raw_gate(path, frames, cancelled, deadline):
    """Inspect every actual decoded RGB frame with zero tolerance and no truncated population."""
    size, digest = RGB_BYTES, hashlib.sha256()
    if not 1 <= len(frames) <= MAX_FRAMES:
        raise ValueError("Decoded lesson frame population exceeds its bounded clock")
    with _open_regular(safe_path(path)) as reader:
        if os.fstat(reader.fileno()).st_size != len(frames) * size:
            raise ValueError("Decoded lesson RGB population is truncated or excessive")
        for frame in frames:
            check_worker(cancelled, deadline)
            body = reader.read(size)
            if len(body) != size or hashlib.sha256(body).hexdigest() != frame["pixel_sha256"]:
                raise ValueError("Finished lesson pixels differ from actual authored domain/glyph/caption frames")
            digest.update(body)
        if reader.read(1):
            raise ValueError("Decoded lesson RGB contains extra frames or bytes")
    return {"status": "passed", "frames": len(frames), "bytes": len(frames) * size, "sha256": digest.hexdigest(), "rgb_tolerance": 0}


def clock_gate(measured, timeline=None):
    """Require complete decoded source-time population and exact measured audio duration."""
    output, audio = measured["output"], measured["audio"]
    tolerance = 1e-6 if timeline is None else .001001
    timeline = legacy_timeline() if timeline is None else timeline
    count, duration = timeline["frame_count"], timeline["duration_seconds"]
    if output["frame_count"] != count or len(output["decoded_frame_seconds"]) != count:
        raise ValueError("Finished lesson dropped or added frames")
    if any(not math.isfinite(v) or abs(v - i / 12) > 1e-6 for i, v in enumerate(output["decoded_frame_seconds"])):
        raise ValueError("Finished lesson frame clocks do not match the exact12fps ledger")
    if not math.isfinite(output["duration_seconds"]) or abs(output["duration_seconds"] - timeline["video_duration_seconds"]) > tolerance or [output["width"], output["height"]] != [640, 360] or output["video_codec"] != "h264":
        raise ValueError("Finished lesson duration/grid/codec is incorrect")
    if audio is None or audio["sample_count"] != timeline["total_samples"] or audio["sample_rate"] != 48000 or not math.isfinite(audio["duration_seconds"]) or abs(audio["duration_seconds"] - duration) > 1e-6:
        raise ValueError("Finished lesson audio sample population differs from the supplied WAV")
    if not math.isfinite(audio["first_seconds"]) or not math.isfinite(audio["end_seconds"]) or abs(audio["first_seconds"]) > 1e-6 or abs(audio["end_seconds"] - duration) > 1e-6:
        raise ValueError("Finished lesson audio clock differs from the exact source interval")


def decoded_pcm(path, expected_samples, cancelled, deadline):
    """Admit the entire decoded RIFF before binding its complete sample and file identities."""
    body = read_bytes(path, 8388608, cancelled, deadline)
    riff_gate(body, expected_samples=expected_samples)
    _, measured = read_pcm(path, 1, cancelled, deadline)
    if measured["sha256"] != hashlib.sha256(body).hexdigest():
        raise ValueError("Decoded lesson audio bytes changed during complete admission")
    return measured


async def finished_gate(spec, directory, frames, records, audio, work, evidence_directory):
    """Join full native measurements against the encoded identity committed before QA."""
    await image_worker(rejoin_files, directory, records, deadline=work.deadline)
    clock = audio.get("timeline", legacy_timeline())
    authored = await image_worker(partial(authored_gate, timeline=clock), spec, directory, frames, deadline=work.deadline)
    measured = await inspect_video(directory / "video.mp4", work)
    clock_gate(measured, clock if spec.schema_version == 2 else None)
    timeline = {"frames": frames, "duration_seconds": clock["video_duration_seconds"], "fps": 12, "dimensions": [640, 360]}
    options = {"max_frames": MAX_FRAMES} if spec.schema_version == 2 else {}
    technical = await full_review(directory / "video.mp4", work, measured, timeline, True, **options)
    if [r["pixel_sha256"] for r in technical["decoded_frames"]] != [r["pixel_sha256"] for r in frames]:
        raise ValueError("Complete decoded frame hashes differ from actual authored frames")
    await image_worker(rejoin_files, directory, records, deadline=work.deadline)
    await extract_evidence(directory / "video.mp4", evidence_directory, work)
    raw = await image_worker(raw_gate, evidence_directory / "decoded.rgb", frames, deadline=work.deadline)
    decoded_audio = await image_worker(decoded_pcm, evidence_directory / "decoded.wav", audio["frames"], deadline=work.deadline)
    if (decoded_audio["frames"], decoded_audio["pcm_sha256"], decoded_audio["sample_rate"], decoded_audio["channels"]) != (audio["frames"], audio["pcm_sha256"], 48000, 1):
        raise ValueError("Finished lesson audio PCM differs from the complete supplied narration")
    evidence = [await image_worker(file_record, evidence_directory / name, evidence_directory, maximum, deadline=work.deadline)
                for name, maximum in [("decoded.rgb", MAX_RGB_BYTES), ("decoded.wav", 8388608)]]
    for committed, measured_identity in zip(evidence, (raw, decoded_audio), strict=True):
        if (committed["sha256"], committed["bytes"]) != (measured_identity["sha256"], measured_identity["bytes"]):
            raise ValueError("Decoded lesson evidence changed after its complete measured identity")
    await image_worker(rejoin_files, directory, records, deadline=work.deadline)
    await image_worker(rejoin_files, evidence_directory, evidence, deadline=work.deadline)
    return {"status": "passed", "authored_source_output": authored, "technical": technical, "decoded_rgb": raw,
            "audio_pcm": {"status": "passed", "frames": decoded_audio["frames"], "pcm_sha256": decoded_audio["pcm_sha256"],
                          "sample_tolerance": 0, "speech_semantics_verified": False}, "evidence": evidence}
