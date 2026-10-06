"""Authored fixture admission and durable mocked render controls; no Remotion load."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from video_explainer_mcp import render_authored as authored
from video_explainer_mcp import render_worker as worker
from video_explainer_mcp import prereqs
from video_explainer_mcp import runner
from video_explainer_mcp.job_store import JobStore
from video_explainer_mcp.jobs import create_job, get_job
from video_explainer_mcp.render_artifacts import file_revision
from video_explainer_mcp.runner import SubprocessResult
from video_explainer_mcp.tools.render_jobs import (
    explainer_render_start, explainer_render_poll, explainer_render_cancel,
)


@pytest.fixture
def fixture_project(tmp_path):
    """Write independently authored canonical WAV and storyboard inputs."""
    project = tmp_path / "projects/fixture"
    for directory in ("storyboard", "assets", "output"):
        (project / directory).mkdir(parents=True, exist_ok=True)
    board = {"scenes": [{"id": "fixture", "title": "Solid card",
                         "audio_duration_seconds": 1.0, "scene_buffer_seconds": 0,
                         "visual_padding_seconds": 0, "audio_file": "fixture.wav",
                         "card_color": "#204060"}]}
    (project / "storyboard/storyboard.json").write_text(json.dumps(board))
    (project / "config.json").write_text("{}")
    samples = b"\0\0" * 48000
    header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(samples), b"WAVE",
                         b"fmt ", 16, 1, 1, 48000, 96000, 2, 16, b"data", len(samples))
    (project / "assets/fixture.wav").write_bytes(header + samples)
    return project


def test_fixture_contract_is_exact_and_fresh(fixture_project):
    contract = authored.authored_project(fixture_project, "720p")
    assert contract["input_props"] == {"color": "#204060", "audio_file": "fixture.wav",
                                        "audio_duration_seconds": 1.0}
    assert contract["expected_output"].endswith("output/final-720p.mp4")
    (fixture_project / "output/final-720p.mp4").write_bytes(b"retained output")
    with pytest.raises(ValueError, match="fresh"):
        authored.authored_project(fixture_project, "720p")


@pytest.mark.parametrize("damage", ["resolution", "scene", "padding", "color", "audio",
                                   "extra", "title", "rate", "frames", "symlink", "boolean"])
def test_unsupported_fixture_refuses_before_dispatch(fixture_project, damage):
    path = fixture_project / "storyboard/storyboard.json"
    board = json.loads(path.read_text())
    scene = board["scenes"][0]
    if damage == "scene":
        board["scenes"].append(dict(scene))
    elif damage == "padding":
        scene["visual_padding_seconds"] = 0.1
    elif damage == "color":
        scene["card_color"] = "url(https://invalid.example/card)"
    elif damage == "audio":
        scene["audio_file"] = "../fixture.wav"
    elif damage == "extra":
        scene["animation"] = "unsupported"
    elif damage == "title":
        scene["title"] = {"not": "text"}
    elif damage == "boolean":
        scene["visual_padding_seconds"] = False
    elif damage in {"rate", "frames"}:
        wav = fixture_project / "assets/fixture.wav"
        data = bytearray(wav.read_bytes())
        if damage == "rate":
            struct.pack_into("<I", data, 24, 44100)
        else:
            data = data[:-2]
        wav.write_bytes(data)
    elif damage == "symlink":
        audio = fixture_project / "assets/fixture.wav"
        audio.rename(fixture_project / "original.wav")
        audio.symlink_to(fixture_project / "original.wav")
    path.write_text(json.dumps(board))
    with pytest.raises((ValueError, OSError)):
        authored.authored_project(fixture_project, "1080p" if damage == "resolution" else "720p")


@pytest.fixture
def selected(fixture_project, monkeypatch):
    """Mock the frozen-runtime boundary, keeping real project/job source checks."""
    cfg = SimpleNamespace(resolved_projects_path=fixture_project.parent, explainer_path="",
                          renderer_entry="/owned/render_entry.mjs", renderer_spec="/owned/spec.json",
                          renderer_spec_sha256="a" * 64, render_timeout=1800)
    binding = {"entry": cfg.renderer_entry, "spec": cfg.renderer_spec,
               "spec_sha256": cfg.renderer_spec_sha256, "entry_revision": {"own": "b" * 64},
               "node": {"path": "/owned/node", "sha256": "c" * 64},
               "fixture_sha256": {name: file_revision(fixture_project / name)["sha256"]
                                   for name in authored.FIXTURE_FILES}}
    monkeypatch.setattr("video_explainer_mcp.jobs.get_config", lambda: cfg)
    monkeypatch.setattr(worker, "get_config", lambda: cfg)
    monkeypatch.setattr("video_explainer_mcp.jobs.authored_binding", lambda config: binding)
    monkeypatch.setattr(worker, "authored_binding", lambda config: binding)
    monkeypatch.setattr(worker, "require_render_ready", AsyncMock())
    return cfg, binding


async def test_authored_admission_dispatch_and_exact_output(fixture_project, selected, monkeypatch):
    row = create_job("fixture")
    claimed = JobStore().claim(row["job_id"], "owned")
    captured = []

    async def render(command, **kwargs):
        captured.append((command, kwargs))
        kwargs["process_started"](123456)
        kwargs["dispatch_updated"]({"node": {"pid": 123456, "group_absent": True},
                                    "browser": {"pid": 123457, "group_absent": True}})
        (fixture_project / "output/final-720p.mp4").write_bytes(b"owned synthetic MP4 boundary")
        return SubprocessResult("retained stdout", "", 0, 0.1, command)

    monkeypatch.setattr(worker, "run_entry", render)
    foreign = AsyncMock()
    monkeypatch.setattr(worker, "run_cli", foreign)
    qualifier = AsyncMock(return_value={"media": {"duration_seconds": 1.0}})
    monkeypatch.setattr(worker, "qualify_render", qualifier)
    exact = AsyncMock(return_value={"frames": 30, "audio_codec": "aac"})
    monkeypatch.setattr(worker, "qualify_authored", exact)
    await worker._execute_render(claimed, "owned")
    retained = get_job(row["job_id"])
    assert retained["status"] == "completed"
    assert retained["attestation"]["verified"] is True
    assert retained["request"]["render_timeout"] == 180
    assert retained["request"]["renderer"]["spec_sha256"] == "a" * 64
    assert retained["request"]["cli_revision"] is None
    assert retained["result"]["dispatch"]["cleanup"]["browser"]["group_absent"] is True
    assert captured[0][0] == ["/owned/node", "/owned/render_entry.mjs", str(fixture_project),
                              "720p", "/owned/spec.json", "a" * 64,
                              "output/final-720p.mp4", row["request"]["execution_token"]]
    foreign.assert_not_awaited()
    qualifier.assert_awaited_once()
    exact.assert_awaited_once()
    assert row["job_id"] not in worker._job_tasks


async def test_changed_authored_binding_fails_durably_before_spawn(selected, monkeypatch):
    row = create_job("fixture")
    claimed = JobStore().claim(row["job_id"], "owned")
    selected[1]["spec_sha256"] = "d" * 64
    spawn = AsyncMock()
    monkeypatch.setattr(worker, "run_entry", spawn)
    with pytest.raises(ValueError, match="Authored renderer changed"):
        await worker._execute_render(claimed, "owned")
    retained = get_job(row["job_id"])
    assert retained["status"] == "failed" and retained["artifact_hashes"] == {}
    assert row["job_id"] not in worker._job_tasks
    spawn.assert_not_awaited()


def test_doctor_rejects_changed_root_frozen_audio(fixture_project, selected, monkeypatch):
    """A format-valid replacement cannot be technically ready under the original freeze."""
    cfg, binding = selected
    cfg.tts_provider = "mock"
    monkeypatch.setattr(prereqs, "get_config", lambda: cfg)
    monkeypatch.setattr(prereqs, "authored_binding", lambda config: {
        **binding, "browser": {"path": "/owned/browser"}})
    monkeypatch.setattr(prereqs.shutil, "which", lambda name: "/owned/" + name)
    audio = fixture_project / "assets/fixture.wav"
    body = bytearray(audio.read_bytes())
    body[-1] = 1
    audio.write_bytes(body)
    report = prereqs.check_prereqs("fixture")
    assert report.all_ok is False
    assert "Root-frozen fixture changed" in report.project["error"]


@pytest.mark.parametrize("stop", ["cancel", "timeout", "failure"])
async def test_authored_terminal_outcomes_keep_identity_and_join(selected, monkeypatch, stop):
    """Cancellation/failure uses the same durable owner and never admits an artifact."""
    selected[0].render_timeout = 1
    row = create_job("fixture")
    claimed = JobStore().claim(row["job_id"], "owned")
    started = asyncio.Event()
    joined = []

    async def render(command, **kwargs):
        kwargs["process_started"](123456)
        started.set()
        try:
            if stop == "failure":
                raise RuntimeError("retained authored boundary failure")
            await asyncio.Event().wait()
        finally:
            kwargs["dispatch_updated"]({"node": {"pid": 123456, "group_absent": True},
                                        "browser": {"pid": 123457, "group_absent": True}})
            joined.append(True)

    monkeypatch.setattr(worker, "run_entry", render)
    task = asyncio.create_task(worker._execute_render(claimed, "owned"))
    await started.wait()
    if stop == "cancel":
        task.cancel()
    with pytest.raises({"cancel": asyncio.CancelledError, "timeout": TimeoutError,
                        "failure": RuntimeError}[stop]):
        await task
    retained = get_job(row["job_id"])
    assert retained["status"] == ("cancelled" if stop == "cancel" else "failed")
    assert retained["external_id"].endswith(row["request"]["execution_token"])
    assert retained["artifact_hashes"] == {} and joined == [True]
    assert retained["result"]["dispatch"]["cleanup"]["browser"]["pid"] == 123457
    assert row["job_id"] not in worker._job_tasks


async def test_unknown_browser_cleanup_cannot_acknowledge_cancel(selected, monkeypatch):
    """A cleanup refusal survives requested cancellation in the durable job result."""
    row = create_job("fixture")
    claimed = JobStore().claim(row["job_id"], "owned")
    started = asyncio.Event()

    async def render(command, **kwargs):
        kwargs["process_started"](123456)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            kwargs["dispatch_updated"]({"browser": {"group_absent": False,
                                                    "launch_custody": "unknown"}})
            raise RuntimeError("Browser cleanup is unverified")

    monkeypatch.setattr(worker, "run_entry", render)
    task = asyncio.create_task(worker._execute_render(claimed, "owned"))
    await started.wait()
    JobStore().cancel(row["job_id"])
    task.cancel()
    with pytest.raises(RuntimeError, match="Browser cleanup is unverified"):
        await task
    retained = get_job(row["job_id"])
    assert retained["status"] == "failed"
    assert retained["result"]["dispatch"]["cleanup"]["browser"]["launch_custody"] == "unknown"
    assert retained["artifact_hashes"] == {} and row["job_id"] not in worker._job_tasks


@pytest.fixture
def qualification_inputs(fixture_project, selected, monkeypatch):
    """Join real owned output/receipt hashes to mocked codec observations."""
    artifact_path = fixture_project / "output/final-720p.mp4"
    artifact_path.write_bytes(b"synthetic output for mocked codec boundary; not rendered media")
    artifact = {"path": str(artifact_path), **file_revision(artifact_path)}
    selected[1]["browser"] = {"path": "/owned/browser", "sha256": "e" * 64}
    request = {"renderer": selected[1], "execution_token": "f" * 32}
    receipt = {"schema": "vrm-authored-render-receipt/r1", "execution_token": "f" * 32,
               "spec_sha256": "a" * 64, "fixture_sha256": selected[1]["fixture_sha256"],
               "composition": authored.COMPOSITION, "browser_sha256": "e" * 64,
               "package_versions": authored.PACKAGES, "output": artifact.copy()}
    receipt_path = fixture_project / "output/final-720p.mp4.receipt.json"
    receipt_path.write_text(json.dumps(receipt))
    monkeypatch.setattr(authored, "codec_executables", lambda: {
        "ffprobe": {"path": "/owned/ffprobe"}, "ffmpeg": {"path": "/owned/ffmpeg"}})
    probe = {"streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720,
         "nb_read_frames": "30", "r_frame_rate": "30/1", "pix_fmt": "yuv420p"},
        {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2}]}
    native = AsyncMock(side_effect=lambda *args: (json.dumps(probe).encode(), b""))
    monkeypatch.setattr(authored, "run_media_process", native)
    return artifact, {"media": {"duration_seconds": 1.0}}, request, receipt_path, receipt, probe, native


async def test_exact_frame_audio_and_receipt_qualification(qualification_inputs):
    artifact, proof, request, _, _, _, native = qualification_inputs
    result = await authored.qualify_authored(artifact, proof, request)
    assert result["frames"] == 30 and result["audio_codec"] == "aac"
    assert result["audio_channels"] == 2
    assert result["playback_verified"] is False
    assert result["receipt"]["execution_token"] == request["execution_token"]
    native.assert_awaited_once()


@pytest.mark.parametrize("damage", ["frames", "fps", "audio", "missing_audio", "duration",
                                   "token", "spec", "output", "receipt_missing", "bytes"])
async def test_bad_frame_audio_or_receipt_cannot_qualify(qualification_inputs, damage):
    artifact, proof, request, receipt_path, receipt, probe, native = qualification_inputs
    if damage == "frames":
        probe["streams"][0]["nb_read_frames"] = "29"
    elif damage == "fps":
        probe["streams"][0]["r_frame_rate"] = "24/1"
    elif damage == "audio":
        probe["streams"][1]["channels"] = 1
    elif damage == "missing_audio":
        probe["streams"].pop()
    elif damage == "duration":
        proof["media"]["duration_seconds"] = 2.0
    elif damage == "token":
        receipt["execution_token"] = "0" * 32
    elif damage == "spec":
        receipt["spec_sha256"] = "0" * 64
    elif damage == "output":
        receipt["output"]["sha256"] = "0" * 64
    elif damage == "bytes":
        from pathlib import Path
        Path(artifact["path"]).write_bytes(b"changed after original output snapshot")
    receipt_path.write_text(json.dumps(receipt))
    if damage == "receipt_missing":
        receipt_path.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        await authored.qualify_authored(artifact, proof, request)


@pytest.mark.parametrize("stale", ["spec", "installed"])
def test_authored_rejects_prior_remotion_version_before_runtime_use(tmp_path, stale):
    """Reject an old authored freeze or metadata without importing Remotion."""
    from pathlib import Path
    import shutil
    source = Path(authored.__file__).parents[2] / "renderer-entry"
    entry = tmp_path / "entry/render_entry.mjs"
    for name in authored.AUTHORED_FILES:
        destination = entry.parent / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, destination)
    versions = dict(authored.PACKAGES)
    assert versions["remotion"] == versions["@remotion/renderer"] == "4.0.532"
    for name, version in versions.items():
        package = entry.parent / "node_modules" / name / "package.json"
        package.parent.mkdir(parents=True, exist_ok=True)
        package.write_text(json.dumps({"name": name, "version":
                                      "4.0.242" if stale == "installed" and
                                      name == "@remotion/renderer" else version}))
    if stale == "spec":
        versions["@remotion/renderer"] = "4.0.242"
    spec = {"schema": "vrm-authored-renderer/r1", "composition": authored.COMPOSITION,
            "entry_sha256": {name: file_revision(entry.parent / name)["sha256"]
                             for name in authored.AUTHORED_FILES}, "package_versions": versions}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    cfg = SimpleNamespace(renderer_entry=str(entry), renderer_spec=str(path),
                          renderer_spec_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    message = "Unsupported authored renderer package versions" if stale == "spec" else (
        "Authored renderer package changed: @remotion/renderer")
    with pytest.raises(ValueError, match=message):
        authored.authored_binding(cfg)


@pytest.mark.parametrize("damage", ["missing", "unfrozen"])
def test_unfrozen_or_missing_lockfile_cannot_admit(tmp_path, damage):
    """Only actual authored bytes are hashed; no installed foreign markers are created."""
    from pathlib import Path
    import shutil
    source = Path(authored.__file__).parents[2] / "renderer-entry"
    entry = tmp_path / "entry/render_entry.mjs"
    for name in authored.AUTHORED_FILES:
        if name == "package-lock.json" and damage == "missing":
            continue
        destination = entry.parent / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, destination)
    spec = {"schema": "vrm-authored-renderer/r1", "composition": authored.COMPOSITION,
            "entry_sha256": {name: file_revision(entry.parent / name)["sha256"]
                             for name in authored.AUTHORED_FILES if name != "package-lock.json"}}
    spec["entry_sha256"]["package-lock.json"] = "0" * 64
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    cfg = SimpleNamespace(renderer_entry=str(entry), renderer_spec=str(path),
                          renderer_spec_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(FileNotFoundError if damage == "missing" else ValueError):
        authored.authored_binding(cfg)
    cfg.renderer_spec_sha256 = "0" * 64
    with pytest.raises(ValueError, match="spec hash changed"):
        authored.authored_binding(cfg)


@pytest.mark.parametrize("stop", ["output_limit", "cancel", "binding"])
async def test_authored_runner_bounds_and_cleanup_are_joined(tmp_path, monkeypatch, stop):
    """The native edge is mocked with real capped pipe readers; no Node is started."""
    process = SimpleNamespace(pid=123456, returncode=None, stdout=asyncio.StreamReader(),
                              stderr=asyncio.StreamReader())
    started, cleanup = asyncio.Event(), []

    async def wait():
        if stop == "cancel":
            await asyncio.Event().wait()
        return 0

    process.wait = wait
    if stop == "output_limit":
        process.stdout.feed_data(b"x" * (1024 * 1024 + 1))
    if stop != "cancel":
        process.stdout.feed_eof()
        process.stderr.feed_eof()
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def reap(proc):
        cleanup.append(proc.pid)

    monkeypatch.setattr(runner, "_reap_uninterruptibly", reap)

    def bind(pid):
        started.set()
        if stop == "binding":
            raise RuntimeError("owned binding rejected")

    task = asyncio.create_task(runner.run_entry(["/owned/node", "/owned/entry"],
                               cwd=str(tmp_path), timeout=10, process_started=bind))
    await started.wait()
    if stop == "cancel":
        task.cancel()
    with pytest.raises(asyncio.CancelledError if stop == "cancel" else RuntimeError):
        await task
    assert cleanup == [123456]
    assert spawn.call_args.kwargs["stdin"] == asyncio.subprocess.DEVNULL


@pytest.mark.parametrize("stop", ["complete", "cancel", "codec_failure"])
async def test_public_authored_start_poll_cancel_journey(fixture_project, selected, monkeypatch, stop):
    """Exercise actual tools/store/worker joins with only renderer and codec edges mocked."""
    running = asyncio.Event()
    joined = []

    async def render(command, **kwargs):
        kwargs["process_started"](123456)
        running.set()
        try:
            if stop == "cancel":
                await asyncio.Event().wait()
            (fixture_project / "output/final-720p.mp4").write_bytes(b"owned mock journey output")
            return SubprocessResult("retained authored stdout", "retained authored stderr", 0, 0.1, command)
        finally:
            joined.append(True)

    monkeypatch.setattr(worker, "run_entry", render)
    qualifier = AsyncMock(return_value={"policy": "mp4-full-decode-v1", "full_decode": True,
                                       "media": {"duration_seconds": 1.0}})

    async def qualify(artifact, resolution):
        if stop == "codec_failure":
            raise ValueError("retained mock codec refusal")
        return await qualifier(artifact, resolution) | {
            "artifact_sha256": artifact["sha256"], "size_bytes": artifact["size_bytes"]}

    monkeypatch.setattr(worker, "qualify_render", qualify)
    monkeypatch.setattr(worker, "qualify_authored", AsyncMock(return_value={"frames": 30, "playback_verified": False}))
    response = await explainer_render_start("fixture")
    assert "job_id" in response and "error" not in response
    await running.wait()
    if stop == "cancel":
        cancelled = await explainer_render_cancel(response["job_id"])
        assert cancelled["status"] == "cancelled"
    else:
        await asyncio.gather(*list(worker._background_tasks))
    polled = await explainer_render_poll(response["job_id"])
    retained = get_job(response["job_id"])
    assert polled["status"] == {"complete": "completed", "cancel": "cancelled",
                                 "codec_failure": "failed"}[stop]
    assert polled["source_revision"] == response["source_revision"]
    assert polled["request_sha256"] == response["request_sha256"]
    assert retained["external_id"].endswith(retained["request"]["execution_token"])
    assert joined == [True] and response["job_id"] not in worker._job_tasks
    if stop != "cancel":
        assert retained["result"]["dispatch"]["stdout"] == "retained authored stdout"
    assert polled["real_renderer_verified"] is False
    if stop == "complete":
        assert polled["artifact_verified"] is True
        assert polled["qualification"]["authored_fixture"]["playback_verified"] is False
    else:
        assert polled["artifact_verified"] is False
    print(json.dumps({"boundary": "mocked renderer/codec; no actual Remotion", "test": stop,
                      "job_id": response["job_id"], "request_sha256": polled["request_sha256"],
                      "source_revision": polled["source_revision"], "status": polled["status"],
                      "operation_id": retained["external_id"], "artifact_hashes": retained["artifact_hashes"],
                      "owned_dispatch_joined": joined == [True], "worker_removed": True}))


def test_authored_nonfrozen_quality_refuses_without_job(selected):
    with pytest.raises(ValueError, match="fast=True"):
        create_job("fixture", fast=False)
    assert JobStore().list_active("render") == []


def test_tree_freeze_detects_added_removed_and_changed_owned_resources(tmp_path):
    """Full populations bind filenames and bytes, including browser resource siblings."""
    tree = tmp_path / "owned-resources"
    tree.mkdir()
    resource = tree / "resource.txt"
    resource.write_text("authored resource")
    original = authored.tree_revision(tree)
    resource.write_text("changed authored resource")
    assert authored.tree_revision(tree) != original
    resource.write_text("authored resource")
    extra = tree / "extra.txt"
    extra.write_text("added authored resource")
    assert authored.tree_revision(tree) != original
    extra.unlink()
    assert authored.tree_revision(tree) == original
    resource.unlink()
    assert authored.tree_revision(tree) != original


def test_tree_freeze_refuses_resource_symlink_escape(tmp_path):
    tree = tmp_path / "owned-resources"
    tree.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("authored external data")
    (tree / "escape").symlink_to(external)
    with pytest.raises(ValueError):
        authored.tree_revision(tree)


async def test_authored_oversize_refuses_before_codec_work(monkeypatch):
    qualifier = AsyncMock()
    monkeypatch.setattr(worker, "qualify_render", qualifier)
    with pytest.raises(ValueError, match="16 MiB"):
        await worker._qualify_output({"size_bytes": 16 * 1024 * 1024 + 1},
                                     {"renderer": {"entry": "/owned/entry"}, "resolution": "720p"})
    qualifier.assert_not_awaited()


async def test_authored_qualification_reports_fixed_quality_without_claims(monkeypatch):
    """Report the selected entry while retaining the requested fast setting and limits."""
    artifact = {"size_bytes": 100, "sha256": "a" * 64}
    request = {"renderer": {"entry": "/owned/entry"}, "resolution": "720p", "fast": True}
    generic = {"renderer_identity": "configured CLI; implementation not attested",
               "real_renderer_verified": False, "visual_audio_semantics": "not_verified"}
    fixture = {"frames": 30, "playback_verified": False, "receipt": {"sha256": "b" * 64}}
    media = AsyncMock(return_value=generic)
    exact = AsyncMock(return_value=fixture)
    monkeypatch.setattr(worker, "qualify_render", media)
    monkeypatch.setattr(worker, "qualify_authored", exact)

    result = await worker._qualify_output(artifact, request)

    assert result["renderer_identity"] == "authored fixed-fixture entry"
    assert result["authored_fixture"] == {
        "frames": 30, "playback_verified": False, "receipt": {"sha256": "b" * 64},
        "quality": "fixed", "fast_applied": False,
    }
    assert result["real_renderer_verified"] is False
    assert result["visual_audio_semantics"] == "not_verified"
    assert request == {"renderer": {"entry": "/owned/entry"}, "resolution": "720p", "fast": True}
    media.assert_awaited_once_with(artifact, "720p")
    exact.assert_awaited_once_with(artifact, generic, request)


async def test_foreign_qualification_reporting_is_unchanged(monkeypatch):
    """Foreign qualification retains its identity and receives no authored quality fields."""
    artifact = {"size_bytes": 100, "sha256": "a" * 64}
    request = {"resolution": "1080p", "fast": True}
    expected = {"renderer_identity": "configured CLI; implementation not attested",
                "real_renderer_verified": False, "visual_audio_semantics": "not_verified",
                "media": {"width": 1920, "height": 1080}}
    media = AsyncMock(return_value=dict(expected))
    exact = AsyncMock()
    monkeypatch.setattr(worker, "qualify_render", media)
    monkeypatch.setattr(worker, "qualify_authored", exact)

    result = await worker._qualify_output(artifact, request)

    assert result == expected
    assert request == {"resolution": "1080p", "fast": True}
    media.assert_awaited_once_with(artifact, "1080p")
    exact.assert_not_awaited()


def test_browser_capture_synchronizes_esm_bindings():
    """Capture namespace launches and restore both bindings through failures."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable for the builtin-only capture control")
    tests = Path(__file__).parent
    result = subprocess.run(
        [node, str(tests / "fixtures/browser_capture.mjs"),
         str(tests.parent / "renderer-entry/render_entry.mjs")],
        capture_output=True, text=True, timeout=10,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "controls": 4, "native_child_spawns": 0,
        "binding_capture_restore": "PASS",
    }
