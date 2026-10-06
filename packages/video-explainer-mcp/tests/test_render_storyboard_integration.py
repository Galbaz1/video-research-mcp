"""Real production admission/dispatch/qualification with native OS edges simulated."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
from unittest.mock import AsyncMock

import pytest

from video_explainer_mcp import prereqs, render_worker as worker
from video_explainer_mcp.job_store import JobStore
from video_explainer_mcp.jobs import create_job, get_job
from video_explainer_mcp.render_artifacts import file_revision
from video_explainer_mcp.render_authored import PACKAGES, tree_revision
from video_explainer_mcp.render_storyboard_binding import PRODUCTION_FILES
from video_explainer_mcp.tools.render_jobs import explainer_render_poll, explainer_render_start

pytestmark = pytest.mark.unit
DIMENSIONS = {"720p": (1280, 720), "1080p": (1920, 1080), "4k": (3840, 2160)}
NODE_PID, BROWSER_PID = 1_000_000_000, 1_000_000_001


def _write(path: Path, body: str | dict | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(body, dict):
        body = json.dumps(body)
    path.write_bytes(body.encode() if isinstance(body, str) else body)


def _project(root: Path, resolution: str) -> Path:
    project = root / "projects/owned"
    _write(
        project / "config.json",
        {
            "paths": {
                "storyboard": "storyboard/storyboard.json",
                "final_video": f"output/final-{resolution}.mp4",
            }
        },
    )
    _write(
        project / "storyboard/storyboard.json",
        {
            "scenes": [
                {
                    "id": "chart",
                    "type": "chart",
                    "title": "Measurements",
                    "audio_file": "voiceover/chart.wav",
                    "audio_duration_seconds": 0.1,
                    "visual_padding_seconds": 0.2,
                    "props": {"values": [2, 5]},
                },
                {
                    "id": "quote",
                    "type": "quote",
                    "title": "Original words",
                    "audio_file": "voiceover/quote.wav",
                    "audio_duration_seconds": 0.3,
                    "visual_padding_seconds": 0.1,
                    "props": {"text": "Source data"},
                },
            ]
        },
    )
    _write(
        project / "scenes/index.ts", "export const sceneRegistry = {chart: Chart, quote: Quote};"
    )
    _write(project / "scenes/Chart.tsx", "export const Chart = ({scene}) => scene.props.values;")
    _write(project / "scenes/Quote.tsx", "export const Quote = ({scene}) => scene.props.text;")
    for name in ("chart", "quote"):
        _write(project / f"voiceover/{name}.wav", b"opaque source-only audio bytes")
    return project


def _runtime(root: Path, project: Path) -> dict:
    runtime = root / "runtime"
    for name in PRODUCTION_FILES:
        _write(runtime / name, f"Independently authored nonexecuted R76 marker: {name}")
    for name, version in PACKAGES.items():
        _write(runtime / "node_modules" / name / "package.json", {"name": name, "version": version})
    binaries = {}
    for name in ("node", "ffmpeg", "ffprobe", "browser"):
        path = root / "binaries" / name
        _write(path, f"Nonexecuted owned R76 {name} marker")
        path.chmod(0o700)
        binaries[name] = {"path": str(path), **file_revision(path)}
    browser = {
        **binaries["browser"],
        "directory": str(root / "binaries"),
        "tree_sha256": tree_revision(root / "binaries"),
    }
    spec = {
        "schema": "vrm-authored-storyboard/r1",
        "composition_id": "Production",
        "entry_sha256": {
            name: file_revision(runtime / name)["sha256"] for name in PRODUCTION_FILES
        },
        "package_versions": PACKAGES,
        "node_modules_sha256": tree_revision(runtime / "node_modules"),
        "node": binaries["node"],
        "browser": browser,
        "ffprobe": binaries["ffprobe"],
        "project_sha256": {
            path.relative_to(project).as_posix(): file_revision(path)["sha256"]
            for path in project.rglob("*")
            if path.is_file()
        },
    }
    spec_path = root / "spec.json"
    _write(spec_path, spec)
    return {
        "project": project,
        "runtime": runtime,
        "spec": spec_path,
        "binaries": binaries,
        "calls": [],
        "render_calls": [],
        "fault": None,
        "output_bytes": 64,
    }


class NativeReply:
    """Finished fake process with real bounded asyncio pipe readers."""

    def __init__(self, body: bytes):
        self.pid, self.returncode = NODE_PID, 0
        self.stdout, self.stderr = asyncio.StreamReader(), asyncio.StreamReader()
        self.stdout.feed_data(body)
        self.stdout.feed_eof()
        self.stderr.feed_eof()

    async def wait(self):
        return self.returncode


def _emit_render(env: dict, command: tuple, options: dict) -> bytes:
    row = JobStore().list_active("render")[0]
    env["job_id"] = row["job_id"]
    request = row["request"]
    env["render_calls"].append((command, options, request))
    custody = Path(options["env"]["VRM_RENDER_CUSTODY_FILE"])
    assert custody.stat().st_mode & 0o777 == 0o600
    _write(
        custody,
        json.dumps(
            {
                "schema": "vrm-browser-custody/r1",
                "execution_token": command[-1],
                "state": "registered",
                "browser_pid": BROWSER_PID,
                "browser_pgid": BROWSER_PID,
            }
        )
        + "\n",
    )
    output = Path(request["render_contract"]["expected_output"])
    output.parent.mkdir(exist_ok=True)
    with output.open("wb") as stream:
        stream.truncate(env["output_bytes"])
    receipt = _render_receipt(request, output)
    _damage_receipt(receipt, env["fault"])
    _write(Path(str(output) + ".receipt.json"), receipt)
    return b"simulated production dispatch stdout"


def _render_receipt(request: dict, output: Path) -> dict:
    width, height = DIMENSIONS[request["resolution"]]
    return {
        "schema": "vrm-authored-storyboard-receipt/r1",
        "execution_token": request["execution_token"],
        "spec_sha256": request["renderer"]["spec_sha256"],
        "project_sha256": request["renderer"]["project_sha256"],
        "entry_sha256": request["renderer"]["entry_sha256"],
        "input_props": request["render_contract"]["input_props"],
        "node_modules_sha256": request["renderer"]["node_modules_sha256"],
        "ffprobe": request["renderer"]["ffprobe"],
        "browser_sha256": request["renderer"]["browser"]["sha256"],
        "package_versions": PACKAGES,
        "fast_requested": request["fast"],
        "fast_applied": request["fast"],
        "quality": {"crf": 28, "x264Preset": "veryfast"}
        if request["fast"]
        else {"crf": 18, "x264Preset": "medium"},
        "composition": {
            "id": "Production",
            "fps": 30,
            "width": width,
            "height": height,
            "durationInFrames": 21,
        },
        "output": {"path": str(output), **file_revision(output)},
        "audio_observations": [
            {"path": "voiceover/chart.wav", "duration_seconds": 0.1},
            {"path": "voiceover/quote.wav", "duration_seconds": 0.3},
        ],
    }


def _damage_receipt(receipt: dict, fault: str | None) -> None:
    if fault == "token":
        receipt["execution_token"] = "another-invocation"
    elif fault == "fast_requested":
        receipt["fast_requested"] = not receipt["fast_requested"]
    elif fault == "fast_applied":
        receipt["fast_applied"] = not receipt["fast_applied"]
    elif fault == "quality":
        receipt["quality"] = {"crf": 99, "x264Preset": "ultrafast"}
    elif fault == "output_sha":
        receipt["output"]["sha256"] = "0" * 64
    elif fault == "props":
        receipt["input_props"]["scenes"][0]["props"]["values"] = [999]
    elif fault == "runtime":
        receipt["node_modules_sha256"] = "0" * 64
    elif fault == "ffprobe":
        receipt["ffprobe"] = {**receipt["ffprobe"], "sha256": "0" * 64}
    elif fault == "audio_extent":
        receipt["audio_observations"][0]["duration_seconds"] = 1.5
    elif fault == "audio_population":
        receipt["audio_observations"].pop()


def _probe(env: dict, command: tuple) -> bytes:
    row = get_job(env["job_id"])
    width, height = DIMENSIONS[row["request"]["resolution"]]
    video = {
        "codec_type": "video",
        "codec_name": "h264",
        "width": width,
        "height": height,
        "pix_fmt": "yuv420p",
        "r_frame_rate": "30/1",
        "nb_read_frames": "21",
    }
    if "-count_frames" not in command:
        return json.dumps({"streams": [video], "format": {"duration": "0.7"}}).encode()
    audio = {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2}
    if env["fault"] == "frames":
        video["nb_read_frames"] = "20"
    elif env["fault"] == "channels":
        audio["channels"] = 1
    return json.dumps({"streams": [video, audio]}).encode()


@pytest.fixture
def production_route(tmp_path, monkeypatch, request):
    resolution = getattr(request, "param", "720p")
    project = _project(tmp_path, resolution)
    env = _runtime(tmp_path, project)
    env["resolution"] = resolution
    for name, value in {
        "EXPLAINER_PATH": str(tmp_path),
        "EXPLAINER_PROJECTS_PATH": str(project.parent),
        "EXPLAINER_RENDERER_ENTRY": str(env["runtime"] / "production_entry.mjs"),
        "EXPLAINER_RENDERER_SPEC": str(env["spec"]),
        "EXPLAINER_RENDERER_SPEC_SHA256": file_revision(env["spec"])["sha256"],
        "R76_PRIVATE_SENTINEL": "must-not-reach-child",
        "CLAUDE_CODE_R76": "must-not-reach-child",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(shutil, "which", lambda name: env["binaries"].get(name, {}).get("path"))

    async def spawn(*command, **options):
        env["calls"].append((command, options))
        name = Path(command[0]).name
        if len(command) == 2 and command[1] in {"--version", "-version"}:
            body = b"v22.1.0\n" if name == "node" else f"{name} source-only version\n".encode()
        elif name == "node" and Path(command[1]).name == "production_entry.mjs":
            body = _emit_render(env, command, options)
        elif name == "ffprobe":
            body = _probe(env, command)
        elif name == "ffmpeg" and "-xerror" in command:
            body = b""
        else:
            raise AssertionError(f"Unexpected simulated native boundary: {command}")
        return NativeReply(body)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(side_effect=spawn))
    monkeypatch.setattr(os, "killpg", lambda *args: _absent_group())
    monkeypatch.setattr(os, "kill", lambda *args: _absent_group())
    monkeypatch.setattr(os, "getpgid", lambda pid: pid)
    return env


def _absent_group():
    raise ProcessLookupError("Simulated native process group is absent")


async def _background(env: dict, fast: bool = True) -> dict:
    response = await explainer_render_start("owned", resolution=env["resolution"], fast=fast)
    assert "error" not in response, response
    await asyncio.gather(*list(worker._background_tasks))
    return get_job(response["job_id"])


def _assert_dispatch(env: dict, row: dict, fast: bool) -> None:
    command, options, request = env["render_calls"][0]
    renderer = request["renderer"]
    expected = [
        renderer["node"]["path"],
        renderer["entry"],
        "--project",
        str(env["project"]),
        "--resolution",
        env["resolution"],
        "--spec",
        renderer["spec"],
        "--spec-sha256",
        renderer["spec_sha256"],
        "--output-relative",
        f"output/final-{env['resolution']}.mp4",
    ]
    if fast:
        expected.append("--fast")
    expected.extend(["--execution-token", request["execution_token"]])
    assert list(command) == expected
    assert options["cwd"] == str(env["runtime"])
    assert options["stdin"] == asyncio.subprocess.DEVNULL and options["start_new_session"]
    assert set(options["env"]) <= {
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "VRM_RENDER_CUSTODY_FILE",
    }
    cleanup = row["result"]["dispatch"]["cleanup"]
    assert cleanup["execution_token"] == command[-1] == request["execution_token"]
    assert cleanup["browser"]["pid"] == BROWSER_PID and cleanup["verified"] is True
    assert row["external_id"] == f"process:{NODE_PID}:{command[-1]}"
    assert len(env["render_calls"]) == 1


@pytest.mark.parametrize("production_route", list(DIMENSIONS), indirect=True)
@pytest.mark.parametrize("fast", [True, False])
@pytest.mark.parametrize("mode", ["background", "blocking"])
async def test_real_sqlite_route_resolution_quality_props_and_custody(production_route, fast, mode):
    env = production_route
    resolution = env["resolution"]
    report = prereqs.check_prereqs("owned", resolution=resolution)
    assert report.all_ok and report.project["input_props"]["width"] == DIMENSIONS[resolution][0]
    if resolution != "720p":
        assert prereqs.check_prereqs("owned").all_ok is False
    if mode == "background":
        row = await _background(env, fast)
    else:
        _, output = await worker._run_render("owned", resolution, fast)
        row = get_job(env["job_id"])
        assert output == row["request"]["render_contract"]["expected_output"]
    assert row["status"] == "completed", row["error"]
    assert row["attestation"]["verified"] is True
    assert row["attempts"] == 1 and row["owner"] is None
    scenes = row["request"]["render_contract"]["input_props"]["scenes"]
    assert [(s["type"], s["from"], s["durationInFrames"]) for s in scenes] == [
        ("chart", 0, 9),
        ("quote", 9, 12),
    ]
    assert [s["props"] for s in scenes] == [{"values": [2, 5]}, {"text": "Source data"}]
    assert [s["audioDurationInFrames"] for s in scenes] == [3, 9]
    assert [s["visualPaddingInFrames"] for s in scenes] == [6, 3]
    _assert_dispatch(env, row, fast)
    polled = await explainer_render_poll(row["job_id"])
    assert polled["status"] == "completed" and polled["artifact_verified"] is True
    assert polled["settings"]["resolution"] == resolution and polled["settings"]["fast"] is fast
    proof = polled["qualification"]["authored_storyboard"]
    assert proof["frames"] == 21 and proof["audio_channels"] == 2
    assert proof["fast_requested"] is fast and proof["fast_applied"] is fast
    receipt = json.loads(Path(proof["receipt"]["path"]).read_text())
    assert receipt["quality"] == (
        {"crf": 28, "x264Preset": "veryfast"} if fast else {"crf": 18, "x264Preset": "medium"}
    )
    assert len(row["artifact_hashes"]) == 2
    assert polled["real_renderer_verified"] is False and proof["playback_verified"] is False
    assert row["job_id"] not in worker._job_tasks


@pytest.mark.parametrize("damage", ["project", "spec", "entry"])
async def test_changed_project_or_binding_fails_durably_before_renderer_spawn(
    production_route, damage
):
    env = production_route
    row, owner = await worker._admit_render("owned", "720p", True)
    calls_before = len(env["calls"])
    changed = {
        "project": env["project"] / "scenes/Chart.tsx",
        "spec": env["spec"],
        "entry": env["runtime"] / "production_entry.mjs",
    }[damage]
    with changed.open("ab") as stream:
        stream.write(b" changed after durable admission")
    with pytest.raises(ValueError):
        await worker._execute_render(row, owner)
    retained = JobStore().get(row["job_id"])
    assert retained["status"] == "failed" and retained["owner"] is None
    assert retained["artifact_hashes"] == {} and retained["external_id"] is None
    assert "output" not in retained["result"] and retained["error"]
    assert env["render_calls"] == [] and len(env["calls"]) == calls_before
    assert row["job_id"] not in worker._job_tasks
    polled = await explainer_render_poll(row["job_id"])
    assert polled["status"] == "failed" and polled["artifact_verified"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "token",
        "fast_requested",
        "fast_applied",
        "quality",
        "output_sha",
        "props",
        "runtime",
        "ffprobe",
        "audio_extent",
        "audio_population",
        "frames",
        "channels",
    ],
)
@pytest.mark.parametrize("fast", [True, False])
async def test_receipt_clock_or_audio_mismatch_never_accepts_artifact(
    production_route, fault, fast
):
    env = production_route
    env["fault"] = fault
    row = await _background(env, fast)
    assert row["status"] == "failed" and row["artifact_hashes"] == {}
    assert row["error"] and "output" not in row["result"]
    expected = {
        "audio_extent": "audio extent differs",
        "audio_population": "population differs",
        "frames": "admitted composition",
        "channels": "AAC 48kHz",
    }.get(fault, "receipt differs")
    assert expected in row["error"]
    assert len(env["render_calls"]) == 1
    assert row["result"]["dispatch"]["cleanup"]["verified"] is True
    assert row["external_id"].endswith(row["request"]["execution_token"])
    polled = await explainer_render_poll(row["job_id"])
    assert polled["status"] == "failed" and polled["artifact_verified"] is False
    assert polled["output_file"] == "" and polled["qualification"] is None
    assert row["job_id"] not in worker._job_tasks


async def test_production_above_old_fixture_bound_reaches_real_qualification(production_route):
    env = production_route
    env["output_bytes"] = 17 * 1024 * 1024
    row = await _background(env, fast=False)
    assert row["status"] == "completed", row["error"]
    assert row["result"]["output"]["size_bytes"] == 17 * 1024 * 1024
    assert row["result"]["output"]["qualification"]["authored_storyboard"]["frames"] == 21
    calls_before = len(env["calls"])
    with pytest.raises(ValueError, match="512 MiB"):
        await worker._qualify_output({"size_bytes": 512 * 1024 * 1024 + 1}, row["request"])
    assert len(env["calls"]) == calls_before


def test_actual_sqlite_exclusive_admission_rejects_second_project_job(production_route):
    first = create_job("owned", fast=False)
    with pytest.raises(RuntimeError, match="already in progress"):
        create_job("owned", fast=True)
    assert [row["job_id"] for row in JobStore().list_active("render")] == [first["job_id"]]
    assert production_route["calls"] == []


@pytest.mark.parametrize("value", [2**53, -(2**53), float(2**53), -float(2**53)])
def test_unsafe_nested_props_refuse_before_real_job_admission(production_route, monkeypatch, value):
    env = production_route
    board_path = env["project"] / "storyboard/storyboard.json"
    board = json.loads(board_path.read_text())
    board["scenes"][0]["props"] = {"rows": [{"cells": [value]}]}
    _write(board_path, board)
    spec = json.loads(env["spec"].read_text())
    spec["project_sha256"]["storyboard/storyboard.json"] = file_revision(board_path)["sha256"]
    _write(env["spec"], spec)
    monkeypatch.setenv("EXPLAINER_RENDERER_SPEC_SHA256", file_revision(env["spec"])["sha256"])
    with pytest.raises(ValueError, match="Scene props.*safe integer"):
        create_job("owned")
    assert JobStore().list_active("render") == [] and env["calls"] == []
