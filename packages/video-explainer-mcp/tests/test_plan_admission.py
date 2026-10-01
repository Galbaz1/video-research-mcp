"""Real transaction controls for retained evidence, injection and render admission."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from unittest.mock import patch

from .test_planning import (
    _api, _approved, _cli_result, _output_cli, _plan, _script, _storyboard, _stored, _write,
)
from .test_planning import planning_project as _planning_project

from video_explainer_mcp.planning_production import freeze_render_source
from video_explainer_mcp.render_artifacts import project_revision
from video_explainer_mcp.tools.pipeline import explainer_step
from video_explainer_mcp.tools.project import explainer_inject

planning_project = _planning_project


async def test_plan_persists_original_citation_identity_after_source_changes(planning_project):
    project, packet = planning_project
    approved = await _approved(project)
    for suffix in ("a", "b"):
        source = next(source for source in packet["sources"] if source["id"] == f"source-{suffix}")
        assert approved["evidence_refs"][f"claim-{suffix}"] == [{
            "source_id": source["id"], "passage_id": "passage",
            "revision": source["revision"], "sha256": source["sha256"],
        }]
    (project / "input/source-b.txt").write_text("Changed later")
    shown = await _api(project, "show")
    assert shown["sources_current"] is False
    assert shown["evidence_refs"] == approved["evidence_refs"] == _stored(project)["evidence_refs"]


async def test_injection_is_denied_while_owned_producer_is_joined(planning_project):
    project, packet = planning_project
    approved = await _approved(project)
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_cli(*args):
        started.set()
        await release.wait()
        _write(project / "script/script.json", _script(approved["plan"], packet))
        return _cli_result(args)

    original = (project / "input/source-a.txt").read_bytes()
    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=slow_cli):
        production = asyncio.create_task(explainer_step(project.name, "script"))
        try:
            await asyncio.wait_for(started.wait(), 2)
            denied = await explainer_inject(project.name, "Unauthorized concurrent edit", "source-a.txt")
            assert "busy" in denied["error"]
            assert (project / "input/source-a.txt").read_bytes() == original
        finally:
            release.set()
            result = await production
    assert result["success"] is True and production.done()


async def test_render_freeze_admits_current_bindings_under_revision_lock(planning_project):
    project, packet = planning_project
    approved = await _approved(project)
    script = _script(approved["plan"], packet)
    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=_output_cli(project, script, _storyboard(script))):
        assert (await explainer_step(project.name, "script"))["success"]
        assert (await explainer_step(project.name, "storyboard"))["success"]
    denied = []
    original = project_revision

    def freeze(directory):
        from video_explainer_mcp.models.planning import PlanRequest
        from video_explainer_mcp.planning import apply_plan

        try:
            apply_plan(project.name, PlanRequest(action="revise", expected_revision=1, plan=approved["plan"]))
        except ValueError as error:
            denied.append(str(error))
        return original(directory)

    with patch("video_explainer_mcp.planning_production.project_revision", side_effect=freeze):
        frozen = freeze_render_source(project)
    assert len(denied) == 1 and "busy" in denied[0]
    assert frozen == project_revision(project)
    assert _stored(project)["revision"] == _stored(project)["approval_revision"] == 1


async def test_repeated_citations_reject_atomically_and_previous_plan_reopens(planning_project):
    project, packet = planning_project
    await _approved(project)
    previous = _stored(project)
    packet["sources"][0]["revision"] = "r" * (300 * 1024)
    repeated = deepcopy(packet["claims"][0])
    repeated["id"] = "claim-a-second"
    packet["claims"].append(repeated)
    assert len(json.dumps(packet).encode()) < 512 * 1024
    _write(project / "input/evidence-packet.json", packet)
    plan = _plan(reject_second=True)
    plan["scenes"][0]["claim_ids"].append("claim-a-second")
    denied = await _api(project, "revise", revision=1, plan=plan)
    assert "512 KiB" in denied["error"]
    assert _stored(project) == previous
    shown = await _api(project, "show")
    assert "error" not in shown and shown["revision"] == 1
    assert shown["evidence_refs"] == previous["evidence_refs"]
    assert (project / "planning.sqlite3").stat().st_size < 8 * 1024 * 1024
