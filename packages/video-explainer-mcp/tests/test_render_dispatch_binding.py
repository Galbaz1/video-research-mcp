"""Console replacement controls with owned files and actual SQLite admission."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from video_explainer_mcp import render_worker as worker
from video_explainer_mcp.job_store import JobStore
from video_explainer_mcp.jobs import create_job, get_job
from video_explainer_mcp.runner import SubprocessResult

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("replacement_stage", ["readiness", "render"])
async def test_console_replacement_rejects_launch_or_completion(
    replacement_stage, tmp_path, monkeypatch,
):
    """Native readiness/CLI edges are simulated; no foreign renderer is invoked."""
    project = tmp_path / "projects/owned"
    (project / "output").mkdir(parents=True)
    (project / "storyboard").mkdir()
    (project / "storyboard/storyboard.json").write_text('{"scenes":[]}')
    (project / "config.json").write_text(json.dumps({"paths": {
        "storyboard": "storyboard/storyboard.json", "final_video": "output/final.mp4",
    }}))
    console = tmp_path / ".venv/bin/video-explainer"
    console.parent.mkdir(parents=True)
    console.write_text("owned admitted console")
    monkeypatch.setenv("EXPLAINER_PATH", str(tmp_path))
    monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(tmp_path / "projects"))
    row = create_job("owned")
    owner = "owned-test"
    claimed = JobStore().claim(row["job_id"], owner)

    async def readiness(project_id):
        await asyncio.sleep(0)
        if replacement_stage == "readiness":
            console.write_text("owned replaced console")

    async def render(*args, **kwargs):
        await asyncio.sleep(0)
        console.write_text("owned replaced console")
        (project / "output/final-720p.mp4").write_bytes(b"synthetic output")
        return SubprocessResult("", "", 0, 0.1, ["simulated render edge"])

    dispatch = AsyncMock(side_effect=render)
    qualifier = AsyncMock()
    source_check = AsyncMock()
    monkeypatch.setattr(worker, "require_render_ready", readiness)
    monkeypatch.setattr(worker, "run_cli", dispatch)
    monkeypatch.setattr(worker, "qualify_render", qualifier)
    monkeypatch.setattr(worker, "source_contract", source_check)
    with pytest.raises(ValueError, match="Render CLI changed after admission"):
        await worker._execute_render(claimed, owner)

    retained = get_job(row["job_id"])
    assert retained["status"] == "failed"
    assert retained["artifact_hashes"] == {}
    assert retained["request"]["cli_revision"] == row["request"]["cli_revision"]
    assert "qualification" not in retained["result"]
    assert row["job_id"] not in worker._job_tasks
    qualifier.assert_not_awaited()
    source_check.assert_not_called()
    if replacement_stage == "readiness":
        dispatch.assert_not_awaited()
    else:
        dispatch.assert_awaited_once()
