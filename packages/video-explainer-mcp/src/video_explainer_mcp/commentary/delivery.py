"""Shard report checks, full-cut assembly with full decode/timing, and delivery refusal."""

from __future__ import annotations

import json
import math
from pathlib import Path

from ..media_process import run_media_process
from ..render_validation import codec_executables
from .project import load
from .shards import current_set
from .store import (
    MAX_SHARD_VIDEO_BYTES, QA_SCHEMA, REPORT_SCHEMA, read_record, revision, sha256, write_once,
)

MEDIA_TIMEOUT = 600
UNDERSTANDING = {"grounded", "degraded_local_repin"}


def _report_errors(report: dict, shard_id: str, shard_sha: str, approval_sha: str, ids: list) -> list[str]:
    errors = []
    expected = {"schema": REPORT_SCHEMA, "shard_id": shard_id, "shard_sha256": shard_sha,
                "approval_sha256": approval_sha, "status": "success"}
    errors += [f"report {key} must be {value}" for key, value in expected.items() if report.get(key) != value]
    segments = report.get("segments") if isinstance(report.get("segments"), list) else []
    if [s.get("segment_id") for s in segments if isinstance(s, dict)] != ids:
        errors.append("report segments differ from the frozen shard")
    for item in segments:
        if not isinstance(item, dict) or item.get("status") != "resolved" or item.get("understanding_mode") not in UNDERSTANDING:
            errors.append("every segment must be resolved with a declared understanding_mode")
            break
    if report.get("unresolved"):
        errors.append("report lists unresolved items")
    checks = report.get("qa_checks")
    if not isinstance(checks, dict) or not checks or not all(v is True for v in checks.values()):
        errors.append("shard QA checks are missing or failed")
    duration = report.get("duration_sec")
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        errors.append("duration_sec must be finite and positive")
    return errors


def _shard(root: Path, name: str, shard_id: str, shard_sha: str) -> tuple[list[str], dict | None]:
    shard = read_record(root / "shards" / name / f"{shard_id}.json")
    approval_path = root / "approvals" / name / f"{shard_id}.json"
    if not approval_path.is_file():
        return [f"{shard_id}: no explicit execution approval recorded"], None
    out = root / "out" / name / shard_id
    try:
        report = read_record(out / "exec_report.json")
        video = revision(out / f"{shard_id}.mp4", MAX_SHARD_VIDEO_BYTES)
    except (OSError, ValueError) as error:
        return [f"{shard_id}: missing execution MP4 or report ({error})"], None
    ids = [s["segment_id"] for s in shard["segments"]]
    errors = _report_errors(report, shard_id, shard_sha, revision(approval_path)["sha256"], ids)
    if video["size_bytes"] == 0 or report.get("output_video") != video:
        errors.append("report output_video differs from the current MP4 bytes")
    return [f"{shard_id}: {e}" for e in errors], {"shard_id": shard_id, "path": str(out / f"{shard_id}.mp4"),
                                                  "video": video, "duration_sec": report.get("duration_sec")}


def check_shards(project_id: str) -> tuple[Path, str, list[dict], list[str]]:
    root, manifest = load(project_id)
    name, index = current_set(root, manifest)
    rows, errors = [], []
    for shard_id, digest in index["shards"].items():
        problems, row = _shard(root, name, shard_id, digest)
        errors += problems
        if row:
            rows.append(row)
    return root, name, rows, errors


async def assemble(project_id: str, tolerance_sec: float) -> dict:
    """Concatenate valid shards, fully decode the result and compare its timing."""
    root, name, rows, errors = check_shards(project_id)
    if errors:
        raise ValueError("Shards are not deliverable: " + "; ".join(errors[:8]))
    claim = root / "full" / ".assembly-claim"
    claim.mkdir()
    primary = None
    try:
        return await _assemble_owned(root, name, rows, tolerance_sec)
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            claim.rmdir()
        except OSError as error:
            if primary is None:
                raise
            primary.add_note(f"Assembly claim cleanup failed: {error}")


async def _assemble_owned(root: Path, name: str, rows: list[dict], tolerance_sec: float) -> dict:
    """Run one assembly while its project claim excludes other assembly requests."""
    final = root / "full" / "commentary.mp4"
    if final.exists() or (root / "full" / "qa.json").exists():
        raise FileExistsError("Final delivery already exists; validate it instead")
    tools = codec_executables()
    listing = root / "full" / "concat.txt"
    quoted = [r["path"].replace("'", "'\\''") for r in rows]
    # Child options prevent a shard from being autodetected as another concat script.
    listing.write_text("".join(f"file '{path}'\noption format_whitelist mov\n"
                               "option protocol_whitelist file\n" for path in quoted), encoding="utf-8")
    ffmpeg, ffprobe = tools["ffmpeg"]["path"], tools["ffprobe"]["path"]
    concat = [ffmpeg, "-v", "error", "-nostdin", "-protocol_whitelist", "file",
              "-format_whitelist", "concat,mov", "-f", "concat", "-safe", "0",
              "-i", str(listing), "-c", "copy", str(final)]
    decode = [ffmpeg, "-v", "error", "-nostdin", "-xerror", "-protocol_whitelist", "file",
              "-f", "mov", "-i", str(final), "-f", "null", "-"]
    probe = [ffprobe, "-v", "error", "-protocol_whitelist", "file", "-f", "mov",
             "-show_entries", "format=duration", "-of", "json", str(final)]
    try:
        await run_media_process(concat, MEDIA_TIMEOUT)
        _, decode_stderr = await run_media_process(decode, MEDIA_TIMEOUT)
        stdout, _ = await run_media_process(probe, MEDIA_TIMEOUT)
    except BaseException as primary:
        try:
            final.unlink(missing_ok=True)
        except OSError as error:
            primary.add_note(f"Unqualified final cleanup failed: {error}")
        raise
    duration = float(json.loads(stdout).get("format", {}).get("duration") or 0)
    expected = sum(r["duration_sec"] for r in rows)
    within = math.isfinite(duration) and abs(duration - expected) <= tolerance_sec
    checks = {"shards_valid": True, "full_decode": not decode_stderr.strip(), "timing": within}
    qa = {"schema": QA_SCHEMA, "set_id": name, "executables": tools,
          "shards": [{"shard_id": r["shard_id"], "video": r["video"], "duration_sec": r["duration_sec"]} for r in rows],
          "final_video": revision(final, MAX_SHARD_VIDEO_BYTES * 8), "commands": [concat, decode, probe],
          "decode_stderr_sha256": sha256(decode_stderr), "timing": {"duration_sec": duration,
          "expected_duration_sec": expected, "tolerance_sec": tolerance_sec}, "checks": checks,
          "overall_pass": all(checks.values())}
    qa["qa_sha256"] = write_once(root / "full" / "qa.json", qa)
    return qa


def validate_delivery(project_id: str) -> dict:
    """Refuse delivery unless every current input, shard, report, MP4 and QA still matches."""
    try:
        root, name, rows, errors = check_shards(project_id)
    except (OSError, ValueError) as error:
        return {"valid": False, "errors": [str(error)]}
    try:
        qa = read_record(root / "full" / "qa.json")
        final = revision(root / "full" / "commentary.mp4", MAX_SHARD_VIDEO_BYTES * 8)
    except (OSError, ValueError) as error:
        return {"valid": False, "set_id": name, "errors": errors + [f"final MP4 or QA missing ({error})"]}
    lineage = [{"shard_id": r["shard_id"], "video": r["video"], "duration_sec": r["duration_sec"]} for r in rows]
    if qa.get("schema") != QA_SCHEMA or qa.get("set_id") != name or qa.get("shards") != lineage:
        errors.append("final QA does not match the current frozen shards and their MP4 bytes")
    if qa.get("final_video") != final:
        errors.append("final MP4 bytes differ from the QA receipt")
    if qa.get("overall_pass") is not True or not all(v is True for v in (qa.get("checks") or {"x": 0}).values()):
        errors.append("final QA did not pass full decode and timing")
    return {"valid": not errors, "set_id": name, "errors": errors, "final_video": final,
            "shards": len(rows), "native_qualification": "requires_actual_ffmpeg_receipts_in_qa"}
