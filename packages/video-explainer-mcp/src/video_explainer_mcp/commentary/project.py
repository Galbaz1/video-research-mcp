"""Durable commentary project: fixed source bytes, ffprobe receipt and execution facts."""

from __future__ import annotations

import json
import math
from pathlib import Path

from ..media_process import run_media_process
from ..render_validation import codec_executables
from .store import (
    MAX_SOURCE_BYTES, PROJECT_SCHEMA, project_root, read_record, revision, sha256, write_once,
)

PROBE_TIMEOUT = 60
SOURCE_FORMATS = "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi,mpeg,mpegts,ogg,asf,flv"
TARGETS = ("analysis_only", "plan_only", "full")
DIRECTORIES = ("plan/watch_notes", "shards", "approvals", "out", "full")
PROBE_FIELDS = ("format=duration,format_name:stream=index,codec_type,codec_name,width,height,"
                "r_frame_rate,sample_aspect_ratio,sample_rate,channels")


def _facts(stdout: bytes) -> dict:
    """Select the first video and audio streams from bounded ffprobe JSON."""
    value = json.loads(stdout)
    streams = value.get("streams") or []
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    duration = float((value.get("format") or {}).get("duration") or 0)
    if not video or not audio:
        raise ValueError("Source movie needs at least one video and one audio stream")
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Source movie has no finite positive duration")
    return {"duration_sec": duration, "format_name": (value.get("format") or {}).get("format_name"),
            "video": {k: video[0].get(k) for k in ("index", "codec_name", "width", "height",
                                                    "r_frame_rate", "sample_aspect_ratio")},
            "audio": {k: audio[0].get(k) for k in ("index", "codec_name", "sample_rate", "channels")},
            "subtitle_streams": [s.get("index") for s in streams if s.get("codec_type") == "subtitle"]}


async def probe_receipt(source: Path) -> dict:
    """Run the pinned ffprobe once and keep its identity, argv and output digest."""
    executables = codec_executables()
    command = [executables["ffprobe"]["path"], "-v", "error", "-protocol_whitelist", "file",
               "-format_whitelist", SOURCE_FORMATS, "-show_entries", PROBE_FIELDS,
               "-of", "json", str(source)]
    stdout, _ = await run_media_process(command, PROBE_TIMEOUT)
    return {"ffprobe": executables["ffprobe"], "command": command,
            "stdout_sha256": sha256(stdout), "facts": _facts(stdout)}


def load(project_id: str) -> tuple[Path, dict]:
    root = project_root(project_id)
    manifest = read_record(root / "project.json")
    if manifest.get("schema") != PROJECT_SCHEMA:
        raise ValueError("Not a movie-commentary project")
    return root, manifest


def verify_source(manifest: dict) -> None:
    """Refuse every downstream step when the fixed source bytes changed."""
    source = manifest["source"]
    current = revision(Path(source["path"]), MAX_SOURCE_BYTES)
    if current != {"sha256": source["sha256"], "size_bytes": source["size_bytes"]}:
        raise ValueError("Source movie bytes changed since project creation")


async def prepare(project_id: str, source_path: str, expected_source_sha256: str, *, target: str,
                  language: str, style_brief: str, source_cut_max_sec: float | None) -> dict:
    """Create one durable project bound to exact source bytes and a measured probe."""
    if target not in TARGETS:
        raise ValueError(f"target must be one of {TARGETS}")
    root = project_root(project_id)
    if root.exists():
        raise FileExistsError("Project already exists; inspect it or choose a new project_id")
    source = Path(source_path).expanduser().absolute()
    before = revision(source, MAX_SOURCE_BYTES)
    if before["sha256"] != expected_source_sha256:
        raise ValueError("Source movie SHA256 differs from the expected revision")
    receipt = await probe_receipt(source)
    if revision(source, MAX_SOURCE_BYTES) != before:
        raise ValueError("Source movie changed during probing")
    duration = receipt["facts"]["duration_sec"]
    ceiling = duration if source_cut_max_sec is None else source_cut_max_sec
    if not 0 < ceiling <= duration:
        raise ValueError("source_cut_max_sec must be positive and within the probed duration")
    for relative in DIRECTORIES:
        (root / relative).mkdir(parents=True, exist_ok=True)
    facts = {"schema": "vrm/movie-commentary-execution-facts/v1", "source_sha256": before["sha256"],
             "duration_sec": duration, "source_cut_max_sec": ceiling,
             "source_cut_basis": "probed_duration" if source_cut_max_sec is None else "caller_asserted",
             "language": language, "bgm_manifest": None, "source_audio_default_mode": "ducked_bed"}
    facts_sha256 = write_once(root / "plan/execution_facts.json", facts)
    write_once(root / "project.json", {
        "schema": PROJECT_SCHEMA, "project_id": project_id, "target": target, "language": language,
        "style_brief": style_brief, "source": {"path": str(source), **before}, "probe": receipt,
        "facts_sha256": facts_sha256, "media_authority": "not_inferred_requires_per_shard_approval"})
    return inspect(project_id)


def inspect(project_id: str) -> dict:
    """Report durable state and the next stage without treating filenames as completion."""
    root, manifest = load(project_id)
    try:
        verify_source(manifest)
        source_state = "current"
    except (OSError, ValueError) as error:
        source_state = f"invalid: {error}"
    notes = root / "plan/watch_notes"
    sets = sorted(p.name for p in (root / "shards").iterdir() if (p / "index.json").is_file())
    final = (root / "full/commentary.mp4").is_file() and (root / "full/qa.json").is_file()
    plan = (root / "plan/editing_plan.json").is_file()
    stage = ("validate_delivery" if final else "approve_execute_or_assemble" if sets and plan
             else "author_plan" if any(notes.glob("*.md")) else "analyze_source")
    return {"project_id": project_id, "project_root": str(root), "target": manifest["target"],
            "source": manifest["source"], "source_state": source_state,
            "probe": manifest["probe"]["facts"], "watch_note_count": len(list(notes.glob("*.md"))),
            "plan_exists": plan, "frozen_shard_sets": sets, "final_video_exists": final,
            "recommended_stage": stage if source_state == "current" else "blocked_source_changed"}
