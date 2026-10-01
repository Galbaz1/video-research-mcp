"""Durable render journeys with exact artifacts and owned local subprocesses."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from video_explainer_mcp.job_store import JobStore
from video_explainer_mcp.jobs import create_job, get_job
from video_explainer_mcp.render_worker import _background_tasks, recover_render_jobs
from video_explainer_mcp.runner import SubprocessResult
from video_explainer_mcp.tools.pipeline import (
    explainer_render,
    explainer_render_cancel,
    explainer_render_poll,
    explainer_render_start,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _controller_native_boundaries(monkeypatch, request):
    """Keep controller outcomes synthetic; the two owned FFmpeg cases decode actual bytes."""
    import video_explainer_mcp.render_worker as worker
    from video_explainer_mcp.render_validation import qualify_render

    monkeypatch.setattr(worker, "require_render_ready", AsyncMock(return_value=None))
    monkeypatch.setattr(worker, "source_contract", lambda directory: {
        "mapped_source_verified": True, "errors": [],
        "test_fixture": "Controller edge stub; no pinned external renderer qualification",
    })

    async def synthetic_qualification(artifact, resolution):
        return {"policy": "mp4-full-decode-v1", "artifact_sha256": artifact["sha256"],
                "size_bytes": artifact["size_bytes"], "full_decode": True,
                "real_renderer_verified": False,
                "test_fixture": "Synthetic controller output; codec subprocess explicitly mocked"}

    monkeypatch.setattr(worker, "qualify_render", qualify_render if request.node.name.startswith(
        "test_real_ffmpeg_") else synthetic_qualification)


def _project(tmp_path, monkeypatch, name="test"):
    project = tmp_path / "projects" / name
    (project / "output").mkdir(parents=True, exist_ok=True)
    (project / "source.json").write_text('{"claim":"owned source"}')
    (project / "storyboard").mkdir(exist_ok=True)
    (project / "storyboard/storyboard.json").write_text('{"scenes":[]}')
    (project / "config.json").write_text(json.dumps({"paths": {
        "storyboard": "storyboard/storyboard.json", "final_video": "output/final.mp4",
    }}))
    monkeypatch.setenv("EXPLAINER_PATH", str(tmp_path))
    monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(tmp_path / "projects"))
    return project


def _cli_result():
    return SubprocessResult("owned mock", "", 0, 0.1, ["render"])


async def _join_workers():
    await asyncio.gather(*list(_background_tasks))
    await asyncio.sleep(0)


async def test_digest_newness_rejects_same_bytes_with_new_timestamp(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)
    output = project / "output/final-720p.mp4"
    output.write_bytes(b"prior video")

    async def render(*args, **kwargs):
        os.utime(output, ns=(time.time_ns(), time.time_ns()))
        return _cli_result()

    with patch("video_explainer_mcp.render_worker.run_cli", side_effect=render):
        result = await explainer_render("test")
    assert "no new nonempty video" in result["error"]


async def test_changed_completed_artifact_cannot_pass_poll(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)
    output = project / "output/final-720p.mp4"

    async def render(*args, **kwargs):
        output.write_bytes(b"accepted output")
        return _cli_result()

    with patch("video_explainer_mcp.render_worker.run_cli", side_effect=render):
        reply = await explainer_render_start("test")
        await _join_workers()
    valid = await explainer_render_poll(reply["job_id"])
    assert valid["status"] == "completed"
    assert valid["artifact_verified"] is True
    original_digest = valid["artifact_hashes"][str(output)]
    output.write_bytes(b"modified output")
    changed = await explainer_render_poll(reply["job_id"])
    assert changed["recorded_status"] == "completed"
    assert changed["status"] == "unknown"
    assert changed["artifact_verified"] is False
    assert changed["output_file"] == ""
    assert changed["artifact_hashes"][str(output)] == original_digest


async def test_queued_restart_recovers_once_without_duplicate_cli(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)
    row = create_job("test")

    async def render(*args, **kwargs):
        (project / "output/final-720p.mp4").write_bytes(b"recovered first launch")
        return _cli_result()

    with patch("video_explainer_mcp.render_worker.run_cli", side_effect=render) as cli:
        await asyncio.gather(recover_render_jobs(), recover_render_jobs())
        await _join_workers()
    recovered = get_job(row["job_id"])
    assert recovered["status"] == "completed"
    assert recovered["attempts"] == 1
    assert recovered["request_sha256"] == row["request_sha256"]
    assert recovered["source_revision"] == row["source_revision"]
    cli.assert_awaited_once()


@pytest.mark.parametrize("drift", ["created", "changed", "deleted"])
async def test_output_written_while_queued_cannot_satisfy_noop_render(drift, tmp_path, monkeypatch):
    """Only output created after dispatch can satisfy the queued render request."""
    project = _project(tmp_path, monkeypatch)
    output = project / "output/final-720p.mp4"
    if drift != "created":
        output.write_bytes(b"admitted retained output")
    row = create_job("test")
    if drift == "deleted":
        output.unlink()
    else:
        output.write_bytes(b"written by another operation while queued")
    with patch("video_explainer_mcp.render_worker.run_cli", return_value=_cli_result()) as cli:
        await recover_render_jobs()
        await _join_workers()
    recovered = get_job(row["job_id"])
    assert recovered["status"] == "failed"
    assert recovered["artifact_hashes"] == {}
    assert recovered["request"]["before_outputs"] == row["request"]["before_outputs"]
    assert recovered["result"]["dispatch"]["before_outputs"] != row["request"]["before_outputs"]
    assert recovered["result"]["dispatch"]["source_revision"] == row["source_revision"]
    assert "outputs changed while queued" in recovered["error"]
    cli.assert_not_awaited()


@pytest.mark.parametrize("change", ["source", "settings", "cli"])
async def test_queued_changed_binding_stops_before_launch(change, tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)
    cli_file = tmp_path / ".venv/bin/video-explainer"
    cli_file.parent.mkdir(parents=True)
    cli_file.write_text("owned CLI v1")
    row = create_job("test")
    if change == "source":
        (project / "source.json").write_text('{"claim":"changed source"}')
    elif change == "settings":
        import video_explainer_mcp.config as config

        config.update_config(explainer_path=str(tmp_path / "changed-cli"))
    else:
        cli_file.write_text("owned CLI v2")
    with patch("video_explainer_mcp.render_worker.run_cli", AsyncMock()) as cli:
        await recover_render_jobs()
        await _join_workers()
    assert get_job(row["job_id"])["status"] == "failed"
    cli.assert_not_awaited()


async def test_mutated_source_during_render_cannot_complete(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)

    async def render(*args, **kwargs):
        (project / "output/final-720p.mp4").write_bytes(b"new output")
        (project / "source.json").write_text('{"claim":"changed during render"}')
        return _cli_result()

    with patch("video_explainer_mcp.render_worker.run_cli", side_effect=render):
        reply = await explainer_render_start("test")
        await _join_workers()
    row = get_job(reply["job_id"])
    assert row["status"] == "failed"
    assert row["artifact_hashes"] == {}
    assert "inputs changed during render" in row["error"]


async def test_orphan_process_is_unknown_without_pid_signal_or_rerun(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    row = create_job("test")
    JobStore().claim(row["job_id"], "old-owner", now=1)
    JobStore().checkpoint(row["job_id"], "old-owner", external_id="process:123:old-token", now=2)
    with (
        patch("video_explainer_mcp.render_worker.run_cli", AsyncMock()) as cli,
        patch("os.killpg") as signal_group,
    ):
        await recover_render_jobs()
        reply = await explainer_render_poll(row["job_id"])
    assert reply["status"] == "unknown"
    assert reply["provider_operation_id"] == "process:123:old-token"
    assert reply["artifact_verified"] is False
    cli.assert_not_awaited()
    signal_group.assert_not_called()


async def test_foreign_running_cancel_is_requested_without_false_ack(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    row = create_job("test")
    JobStore().claim(row["job_id"], "another-process")
    JobStore().checkpoint(row["job_id"], "another-process", external_id="process:123:foreign-token")
    with patch("os.killpg") as signal_group:
        reply = await explainer_render_cancel(row["job_id"])
    assert reply["status"] == "cancel_requested"
    assert reply["cancellation_acknowledged"] is False
    assert "cannot verify termination" in reply["error"]
    signal_group.assert_not_called()
    assert not JobStore().checkpoint(row["job_id"], "another-process", status="completed")


async def test_queued_cancel_is_immediate_and_never_launched(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    row = create_job("test")
    reply = await explainer_render_cancel(row["job_id"])
    assert reply["status"] == "cancelled"
    assert reply["cancellation_acknowledged"] is True
    with patch("video_explainer_mcp.render_worker.run_cli", AsyncMock()) as cli:
        await recover_render_jobs()
    cli.assert_not_awaited()


async def test_queue_drain_keeps_two_workers_and_all_denominator_items(tmp_path, monkeypatch):
    rows = []
    for name in ["one", "two", "three", "four"]:
        _project(tmp_path, monkeypatch, name)
        rows.append(create_job(name))
    active, maximum = 0, 0

    async def render(*args, **kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.03)
        project = tmp_path / "projects" / args[1]
        (project / "output/final-720p.mp4").write_bytes(args[1].encode())
        active -= 1
        if args[1] == "three":
            raise RuntimeError("retained failure")
        return _cli_result()

    with patch("video_explainer_mcp.render_worker.run_cli", side_effect=render) as cli:
        await recover_render_jobs()
        await _join_workers()
    assert maximum == 2
    assert cli.await_count == 4
    statuses = [get_job(row["job_id"])["status"] for row in rows]
    assert statuses.count("completed") == 3
    assert statuses.count("failed") == 1
    assert all(get_job(row["job_id"])["attempts"] == 1 for row in rows)


def _owned_ffmpeg_cli(tmp_path, monkeypatch, seconds):
    """A small, owned CLI invokes installed FFmpeg without any provider or install."""
    ffmpeg = shutil.which("ffmpeg")
    if os.name != "posix" or not ffmpeg or not shutil.which("ffprobe"):
        pytest.skip("POSIX ownership and locally installed FFmpeg/FFprobe required")
    project = _project(tmp_path, monkeypatch)
    script = tmp_path / ".venv/bin/video-explainer"
    script.parent.mkdir(parents=True)
    script.write_text(f"""#!{sys.executable}
import json, pathlib, subprocess, sys
root = pathlib.Path(sys.argv[sys.argv.index("--projects-dir")+1])
name = sys.argv[sys.argv.index("render")+1]
out = root/name/"output"
proc = subprocess.Popen([{ffmpeg!r}, "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi", "-i", "color=c=blue:s=1280x720:r=1:d={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(out/"final-720p.mp4")])
(out/"owned-process.json").write_text(json.dumps({{"child_pid":proc.pid}}))
sys.exit(proc.wait())
""")
    script.chmod(0o700)
    return project


async def _wait_for_marker(project):
    marker = project / "output/owned-process.json"
    async with asyncio.timeout(5):
        while not marker.exists():
            await asyncio.sleep(0.02)
    return json.loads(marker.read_text())


async def test_real_ffmpeg_keeps_heartbeat_and_verified_restart_poll(tmp_path, monkeypatch):
    project = _owned_ffmpeg_cli(tmp_path, monkeypatch, 3)
    reply = await explainer_render_start("test")
    await _wait_for_marker(project)
    before = get_job(reply["job_id"])
    await asyncio.sleep(1.2)
    during = get_job(reply["job_id"])
    assert during["status"] == "running"
    assert during["lease_until"] > before["lease_until"] + 0.5
    assert during["external_id"].startswith("process:")
    await _join_workers()
    await recover_render_jobs()
    after = await explainer_render_poll(reply["job_id"])
    assert after["status"] == "completed"
    assert after["artifact_verified"] is True
    assert after["provider_operation_id"] == during["external_id"]
    assert after["source_revision"] == reply["source_revision"]
    assert after["request_sha256"] == reply["request_sha256"]
    assert after["attempts"] == 1
    assert Path(after["output_file"]).stat().st_size > 0


async def test_real_ffmpeg_cancel_joins_owned_process_group(tmp_path, monkeypatch):
    project = _owned_ffmpeg_cli(tmp_path, monkeypatch, 10)
    reply = await explainer_render_start("test")
    marker = await _wait_for_marker(project)
    owner = get_job(reply["job_id"])["owner"]
    cancelled = await explainer_render_cancel(reply["job_id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancellation_acknowledged"] is True
    assert not _background_tasks
    async with asyncio.timeout(5):
        while True:
            try:
                os.kill(marker["child_pid"], 0)
            except ProcessLookupError:
                break
            await asyncio.sleep(0.02)
    assert not JobStore().checkpoint(reply["job_id"], owner, status="completed")
    assert (await explainer_render_poll(reply["job_id"]))["status"] == "cancelled"


@pytest.mark.parametrize("unsafe", ["input_symlink", "output_symlink", "outside_project", "fifo"])
async def test_unbound_source_or_output_paths_stop_before_cli(unsafe, tmp_path, monkeypatch):
    """A source receipt cannot omit nonregular inputs or follow uncontrolled project/output links."""
    project = _project(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    original = outside / "private.json"
    original.write_text('{"private":"owned test fixture"}')
    name = "test"
    if unsafe == "input_symlink":
        (project / "external.json").symlink_to(original)
    elif unsafe == "output_symlink":
        (project / "output").rmdir()
        (project / "output").symlink_to(outside, target_is_directory=True)
    elif unsafe == "outside_project":
        (project.parent / "escape").symlink_to(outside, target_is_directory=True)
        name = "escape"
    else:
        os.mkfifo(project / "unbound.pipe")
    with patch("video_explainer_mcp.render_worker.run_cli", AsyncMock()) as cli:
        result = await explainer_render_start(name)
    assert "error" in result
    cli.assert_not_awaited()
    assert original.read_text() == '{"private":"owned test fixture"}'


async def test_mapped_renderer_source_changed_after_dispatch_cannot_be_accepted(tmp_path, monkeypatch):
    """A source-contract edge transition denies output before codec acceptance."""
    project = _project(tmp_path, monkeypatch)
    monkeypatch.setattr("video_explainer_mcp.render_worker.source_contract", lambda directory: {
        "mapped_source_verified": False, "errors": ["owned source changed after dispatch"],
    })
    qualifier = AsyncMock()
    monkeypatch.setattr("video_explainer_mcp.render_worker.qualify_render", qualifier)

    async def render(*args, **kwargs):
        (project / "output/final-720p.mp4").write_bytes(b"Synthetic unaccepted renderer output")
        return _cli_result()

    with patch("video_explainer_mcp.render_worker.run_cli", side_effect=render) as cli:
        reply = await explainer_render_start("test")
        await _join_workers()
    row = get_job(reply["job_id"])
    assert row["status"] == "failed" and row["artifact_hashes"] == {}
    assert "changed after dispatch" in row["error"]
    cli.assert_awaited_once()
    qualifier.assert_not_awaited()


async def test_fresh_wrong_named_video_cannot_satisfy_exact_output_contract(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)
    qualifier = AsyncMock()
    monkeypatch.setattr("video_explainer_mcp.render_worker.qualify_render", qualifier)

    async def render(*args, **kwargs):
        (project / "output/unrelated-fresh.mp4").write_bytes(b"Synthetic different output")
        return _cli_result()

    with patch("video_explainer_mcp.render_worker.run_cli", side_effect=render):
        reply = await explainer_render_start("test")
        await _join_workers()
    row = get_job(reply["job_id"])
    assert row["status"] == "failed" and row["artifact_hashes"] == {}
    assert "expected current-request MP4" in row["error"]
    qualifier.assert_not_awaited()
