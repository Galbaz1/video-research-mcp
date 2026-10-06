"""Authored commentary fixtures with a mocked native ffprobe/ffmpeg boundary (no media)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from video_explainer_mcp.commentary import delivery, project
from video_explainer_mcp.commentary.store import PLAN_SCHEMA, REPORT_SCHEMA
from video_explainer_mcp.tools.commentary import (
    ShardApproval, commentary_approve_shard, commentary_freeze_shards, commentary_prepare,
)

PROBE = {"format": {"duration": "120.0", "format_name": "mov,mp4,m4a"},
         "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1280,
                      "height": 720, "r_frame_rate": "24/1", "sample_aspect_ratio": "1:1"},
                     {"index": 1, "codec_type": "audio", "codec_name": "aac", "sample_rate": "48000",
                      "channels": 2}]}
TOOLS = {"ffprobe": {"path": "/pinned/ffprobe", "sha256": "1" * 64, "size_bytes": 1},
         "ffmpeg": {"path": "/pinned/ffmpeg", "sha256": "2" * 64, "size_bytes": 2}}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Projects under tmp; every native command is recorded and answered by the mock."""
    monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(tmp_path / "projects"))
    state = {"calls": [], "final_duration": 4.0, "decode_error": None}

    async def run(command, timeout, **_):
        state["calls"].append(command)
        if command[0] == TOOLS["ffprobe"]["path"]:
            if command[-1].endswith("commentary.mp4"):
                return json.dumps({"format": {"duration": str(state["final_duration"])}}).encode(), b""
            return json.dumps(PROBE).encode(), b""
        if "concat" in command:
            Path(command[-1]).write_bytes(b"R199 mock concatenated cut (not media)")
            return b"", b""
        if state["decode_error"]:
            raise RuntimeError(state["decode_error"])
        return b"", b""

    for module in (project, delivery):
        monkeypatch.setattr(module, "codec_executables", lambda: TOOLS)
        monkeypatch.setattr(module, "run_media_process", run)
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"R199 caller-authored dummy movie bytes (not media)")
    return {"tmp": tmp_path, "source": source, "state": state, "root": tmp_path / "projects/.movie-commentary/film"}


async def prepare(env, **extra) -> dict:
    return await commentary_prepare(project_id="film", source_path=str(env["source"]),
                                    expected_source_sha256=sha(env["source"].read_bytes()), **extra)


def segment(index: int, **changes) -> dict:
    value = {"segment_id": f"SEG_{index:04d}", "narration": {"text": f"Narration line {index}."},
             "visual_plan": {"rough_interval_sec": [10.0 * index, 10.0 * index + 5],
                             "movie_locator": {"evidence_refs": [f"plan/watch_notes/n{index}.md"]}},
             "audio_plan": {"source_audio_mode": "ducked_bed", "bgm_mode": "none"}}
    value.update(changes)
    return value


def author(env, count: int = 3, segments=None, script=None, source_sha=None) -> list[dict]:
    root = env["root"]
    for index in range(1, count + 1):
        (root / f"plan/watch_notes/n{index}.md").write_text(f"Caller watch note {index}.\n")
    segments = segments or [segment(i) for i in range(1, count + 1)]
    plan = {"schema": PLAN_SCHEMA, "segments": segments,
            "source_sha256": source_sha or sha(env["source"].read_bytes())}
    (root / "plan/editing_plan.json").write_text(json.dumps(plan))
    lines = script if script is not None else "".join(
        f"{s['segment_id']}\n{s['narration']['text']}\n" for s in segments if isinstance(s, dict))
    (root / "plan/narration_script.md").write_text(lines)
    return segments


async def frozen(env, count=3, per_shard=2) -> dict:
    await prepare(env)
    author(env, count)
    return await commentary_freeze_shards(project_id="film", segments_per_shard=per_shard)


def approval(env, shard_sha: str, **changes) -> ShardApproval:
    values = {"approved_by": "operator (caller-declared)", "shard_sha256": shard_sha,
              "source_sha256": sha(env["source"].read_bytes()),
              "media_authority": "Caller states it holds rights for this dummy fixture"}
    return ShardApproval(**{**values, **changes})


async def execute(env, freeze: dict, shard_id: str, duration=2.0, **report_changes) -> dict:
    """Stand in for host execution of one approved shard: MP4 bytes plus a measured report."""
    scope = await commentary_approve_shard(project_id="film", shard_id=shard_id,
                                           approval=approval(env, freeze["shards"][shard_id]))
    video = Path(scope["output_video"])
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(f"R199 mock shard {shard_id} (not media)".encode())
    shard = json.loads(Path(scope["shard_path"]).read_text())
    report = {"schema": REPORT_SCHEMA, "shard_id": shard_id, "shard_sha256": freeze["shards"][shard_id],
              "approval_sha256": scope["approval_sha256"], "status": "success",
              "segments": [{"segment_id": s["segment_id"], "status": "resolved",
                            "understanding_mode": "grounded"} for s in shard["segments"]],
              "output_video": {"sha256": sha(video.read_bytes()), "size_bytes": video.stat().st_size},
              "duration_sec": duration, "qa_checks": {"decode": True, "loudness": True}, "unresolved": []}
    report.update(report_changes)
    Path(scope["output_report"]).write_text(json.dumps(report))
    return scope
