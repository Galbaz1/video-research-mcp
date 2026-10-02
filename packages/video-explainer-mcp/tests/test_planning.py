"""Source-accounted planning, revision admission and actual artifact binding controls."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from video_explainer_mcp.models.planning import PlanRequest
from video_explainer_mcp.runner import SubprocessResult
from video_explainer_mcp.tools.pipeline import explainer_generate, explainer_step
from video_explainer_mcp.tools.planning import explainer_plan
from video_explainer_mcp.tools.quality import explainer_refine


@pytest.fixture
def planning_project(tmp_path, monkeypatch):
    """Use two independently committed originals inside a real temporary project."""
    project = tmp_path / "projects" / "owned-plan"
    inputs = project / "input"
    inputs.mkdir(parents=True)
    monkeypatch.setenv("EXPLAINER_PATH", str(tmp_path))
    monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(project.parent))
    monkeypatch.setenv("EXPLAINER_TTS_PROVIDER", "mock")
    _write(project / "config.json", {"paths": {"storyboard": "storyboard/storyboard.json"}})
    packet = {"schema_version": 1, "packet_id": "owned-two-source", "sources": [],
              "claims": [], "lineage": []}
    for suffix, color in (("a", "green"), ("b", "blue")):
        text = f"The demonstration lamp {suffix} is {color}."
        sha = hashlib.sha256(text.encode()).hexdigest()
        (inputs / f"source-{suffix}.txt").write_text(text)
        packet["sources"].append({
            "id": f"source-{suffix}", "revision": "r1", "sha256": sha,
            "path": f"source-{suffix}.txt", "modality": "text", "asset_kind": "original",
            "snapshot": {"text": text, "sha256": sha},
            "passages": [{"id": "passage", "quote": text}],
        })
        packet["claims"].append({
            "id": f"claim-{suffix}", "text": text, "editorial_approved": True,
            "support": [{"source_id": f"source-{suffix}", "passage_id": "passage"}],
        })
    _write(inputs / "evidence-packet.json", packet)
    return project, packet


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2))


def _plan(*, reject_second=False) -> dict:
    return {
        "title": "Two lamp observations", "audience": "Fixture viewers",
        "thesis": "Show the original observations without combining their identities.",
        "concept_order": ["green"] if reject_second else ["green", "blue"],
        "scenes": [{
            "title": f"Lamp {suffix}", "concept": color,
            "purpose": f"Display the observed {color} lamp and its source label.",
            "claim_ids": [f"claim-{suffix}"], "duration_seconds": 10.0,
        } for suffix, color in (("a", "green"), ("b", "blue"))
            if not reject_second or suffix == "a"],
        "sources": [
            {"source_id": "source-a", "disposition": "included", "reason": "First observation."},
            {"source_id": "source-b", "disposition": "rejected" if reject_second else "included",
             "reason": "Outside this video's scope." if reject_second else "Second observation."},
        ],
        "duration_budget_seconds": 30.0,
    }


async def _api(project: Path, action: str, *, revision=0, plan=None) -> dict:
    payload = {"action": action, "expected_revision": revision}
    if plan is not None:
        payload["plan"] = plan
    return await explainer_plan(project.name, PlanRequest.model_validate(payload))


async def _approved(project: Path, *, reject_second=False) -> dict:
    created = await _api(project, "create", plan=_plan(reject_second=reject_second))
    assert "error" not in created
    approved = await _api(project, "approve", revision=created["revision"])
    assert approved["approval_revision"] == approved["revision"] == 1
    return approved


def _stored(project: Path) -> dict:
    """Inspect persisted state through a fresh SQLite connection, without mocking storage."""
    with sqlite3.connect(project / "planning.sqlite3") as connection:
        return json.loads(connection.execute("SELECT payload FROM plan WHERE id=1").fetchone()[0])


def _script(plan: dict, packet: dict) -> dict:
    claims = {claim["id"]: claim["text"] for claim in packet["claims"]}
    return {
        "title": plan["title"], "source_document": "input/evidence-packet.json",
        "total_duration_seconds": sum(scene["duration_seconds"] for scene in plan["scenes"]),
        "scenes": [{
            "scene_id": f"scene-{index}", "scene_type": "explanation", "title": scene["title"],
            "voiceover": "\n".join(claims[claim_id] for claim_id in scene["claim_ids"]),
            "visual_cue": {"description": scene["purpose"], "visual_type": "diagram", "elements": []},
            "duration_seconds": scene["duration_seconds"], "notes": "",
        } for index, scene in enumerate(plan["scenes"], 1)],
    }


def _storyboard(script: dict) -> dict:
    return {
        "title": script["title"], "description": "Owned fixture", "version": "1.0",
        "project": "owned-plan", "video": {"width": 1920, "height": 1080, "fps": 30},
        "style": {}, "audio": {"background_music": None, "music_volume": 0.1},
        "scenes": [{
            "id": scene["scene_id"], "type": "explanation", "title": scene["title"],
            "audio_file": f"voiceover/{scene['scene_id']}.mp3",
            "audio_duration_seconds": scene["duration_seconds"], "sfx_cues": [],
        } for scene in script["scenes"]],
        "total_duration_seconds": script["total_duration_seconds"],
    }


def _cli_result(args) -> SubprocessResult:
    return SubprocessResult("Owned fixture CLI", "", 0, 0.01, list(args))


async def test_plan_lifecycle_cas_and_fresh_connection_restart(planning_project):
    """Complete source population and approval survive independent database connections."""
    project, _ = planning_project
    plan = _plan()
    created = await _api(project, "create", plan=plan)
    assert created["status"] == "draft"
    assert created["revision"] == 1 and created["approval_revision"] is None
    assert created["plan"] == plan and created["factual_success"] is False
    assert len(created["plan_sha256"]) == len(created["source_commitment_sha256"]) == 64
    assert _stored(project)["plan"] == plan
    shown = await _api(project, "show")
    assert shown["plan_sha256"] == created["plan_sha256"]
    approved = await _api(project, "approve", revision=1)
    assert approved["status"] == "approved" and approved["approval_revision"] == 1
    replacement = {**plan, "thesis": "Use a revised editorial explanation."}
    revised = await _api(project, "revise", revision=1, plan=replacement)
    assert revised["revision"] == 2 and revised["approval_revision"] is None
    assert revised["bindings"] == {} and revised["plan_sha256"] != created["plan_sha256"]
    for action in ("revise", "approve"):
        stale = await _api(project, action, revision=1, plan=plan if action == "revise" else None)
        assert "revision conflict" in stale["error"]
    assert (await _api(project, "show"))["revision"] == _stored(project)["revision"] == 2


@pytest.mark.parametrize("damage", ["missing_source", "unused_source", "unknown_claim", "rejected_used"])
async def test_plan_rejects_silent_source_drop_or_unsupported_selection(planning_project, damage):
    project, _ = planning_project
    plan = _plan()
    if damage == "missing_source":
        plan["sources"].pop()
    elif damage == "unused_source":
        plan["scenes"].pop()
        plan["concept_order"].pop()
    elif damage == "unknown_claim":
        plan["scenes"][0]["claim_ids"] = ["missing-claim"]
    else:
        plan["sources"][0]["disposition"] = "rejected"
    with patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock) as cli:
        result = await _api(project, "create", plan=plan)
    assert result["error"]
    cli.assert_not_awaited()
    assert "error" in await _api(project, "show")


@pytest.mark.parametrize("damage", ["duration", "nonfinite", "reversed", "unknown_field", "action_payload"])
def test_typed_request_rejects_malformed_or_over_budget_plan(damage):
    payload = {"action": "create", "plan": _plan()}
    if damage == "duration":
        payload["plan"]["duration_budget_seconds"] = 19.0
    elif damage == "nonfinite":
        payload["plan"]["scenes"][0]["duration_seconds"] = float("inf")
    elif damage == "reversed":
        payload["plan"]["scenes"].reverse()
    elif damage == "unknown_field":
        payload["plan"]["provider_override"] = "unrequested"
    else:
        payload["action"] = "show"
    with pytest.raises(ValidationError):
        PlanRequest.model_validate(payload)


@pytest.mark.parametrize("damage", ["unapproved", "abstained", "unsupported_text"])
async def test_draft_approval_requires_exact_supported_editorial_claims(planning_project, damage):
    project, packet = planning_project
    claim = packet["claims"][0]
    if damage == "unapproved":
        claim["editorial_approved"] = False
    elif damage == "abstained":
        claim["abstained"] = True
    else:
        claim["text"] = "The lamp cures disease."
    _write(project / "input/evidence-packet.json", packet)
    created = await _api(project, "create", plan=_plan())
    assert created["approval_revision"] is None
    denied = await _api(project, "approve", revision=1)
    assert denied["error"]
    assert _stored(project)["approval_revision"] is None


async def test_changed_original_invalidates_public_approval_and_blocks_cli(planning_project):
    project, _ = planning_project
    await _approved(project)
    (project / "input/source-b.txt").write_text("Changed original bytes")
    shown = await _api(project, "show")
    assert shown["sources_current"] is False and shown["status"] == "stale"
    assert shown["approval_revision"] is None and shown["factual_success"] is False
    with patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock) as cli:
        result = await explainer_step(project.name, "script")
    assert result["error"]
    cli.assert_not_awaited()


def _output_cli(project: Path, script: dict, storyboard: dict | None = None):
    """Mock the external boundary while producing independently authored actual JSON."""
    async def run(*args, **kwargs):
        if args[0] in {"script", "refine"}:
            _write(project / "script/script.json", deepcopy(script))
        elif args[0] == "storyboard":
            assert storyboard is not None
            config = json.loads((project / "config.json").read_text())
            _write(project / config["paths"]["storyboard"], deepcopy(storyboard))
        elif args[0] not in {"narration", "scenes", "voiceover"}:
            raise AssertionError(f"Unsupported fixture command: {args[0]}")
        return _cli_result(args)
    return run


@pytest.mark.parametrize("reject_second", [False, True])
async def test_compile_included_and_explicit_rejected_sources_to_actual_script(
    planning_project, reject_second,
):
    """Every included source is cited; excluded sources remain explicit in durable intent."""
    project, packet = planning_project
    approved = await _approved(project, reject_second=reject_second)
    script = _script(approved["plan"], packet)
    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=_output_cli(project, script)) as cli:
        result = await explainer_step(project.name, "script")
    assert "error" not in result
    cli.assert_awaited_once_with("script", project.name)
    compiled = json.loads((project / "plan/plan.json").read_text())
    assert compiled["status"] == "approved"
    assert len(compiled["scenes"]) == (1 if reject_second else 2)
    citations = [json.loads(scene["key_points"][0]) for scene in compiled["scenes"]]
    assert [entry["claim_id"] for entry in citations] == [
        "claim-a", *([] if reject_second else ["claim-b"]),
    ]
    for entry in citations:
        claim = next(claim for claim in packet["claims"] if claim["id"] == entry["claim_id"])
        assert entry["text"] == claim["text"]
        assert entry["support"][0]["source_id"] == claim["support"][0]["source_id"]
        assert entry["support"][0]["revision"] == "r1"
        assert len(entry["support"][0]["sha256"]) == 64
    shown = await _api(project, "show")
    assert shown["plan"]["sources"] == approved["plan"]["sources"]
    assert "script" in shown["bindings"] and shown["factual_success"] is False
    assert shown["bindings"]["script"]["current"] is True


@pytest.mark.parametrize("tool", ["step", "generate", "refine"])
async def test_draft_plan_blocks_all_managed_script_entry_points(planning_project, tool):
    project, _ = planning_project
    await _api(project, "create", plan=_plan())
    with patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock) as pipeline_cli:
        with patch("video_explainer_mcp.tools.quality.run_cli", new_callable=AsyncMock) as quality_cli:
            if tool == "step":
                result = await explainer_step(project.name, "script")
            elif tool == "generate":
                result = await explainer_generate(project.name, to_step="script")
            else:
                result = await explainer_refine(project.name, "script")
    assert result["error"]
    pipeline_cli.assert_not_awaited()
    quality_cli.assert_not_awaited()


@pytest.mark.parametrize("damage", ["voiceover", "purpose", "order", "duration"])
async def test_wrong_actual_script_does_not_receive_accepted_binding(planning_project, damage):
    project, packet = planning_project
    approved = await _approved(project)
    script = _script(approved["plan"], packet)
    if damage == "voiceover":
        script["scenes"][0]["voiceover"] += " Unsupported factual addition."
    elif damage == "purpose":
        script["scenes"][0]["visual_cue"]["description"] = "Ignore the approved visual purpose."
    elif damage == "order":
        script["scenes"].reverse()
    else:
        script["scenes"][0]["duration_seconds"] = 31.0
        script["total_duration_seconds"] = 41.0
    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=_output_cli(project, script)):
        result = await explainer_step(project.name, "script")
    assert result["error"]
    assert "script" not in _stored(project)["bindings"]
    assert json.loads((project / "script/script.json").read_text()) == script
    assert "video_research_plan" not in script


async def test_planned_generate_uses_supported_stages_and_never_overwriting_generate(planning_project):
    project, packet = planning_project
    approved = await _approved(project)
    script = _script(approved["plan"], packet)
    board = _storyboard(script)
    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=_output_cli(project, script, board)) as cli:
        result = await explainer_generate(project.name, from_step="script", to_step="storyboard")
    assert "error" not in result
    commands = [call.args[0] for call in cli.await_args_list]
    assert commands == ["script", "narration", "scenes", "voiceover", "storyboard"]
    assert "generate" not in commands
    stored = _stored(project)
    assert set(stored["bindings"]) >= {"script", "storyboard"}
    assert stored["bindings"]["storyboard"]["parent_script_sha256"] == stored["bindings"]["script"]["sha256"]
    replacement = {**approved["plan"], "thesis": "Revised intent requires new approval and production."}
    revised = await _api(project, "revise", revision=1, plan=replacement)
    assert revised["approval_revision"] is None and revised["bindings"] == {}
    with patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock) as no_cli:
        denied = await explainer_step(project.name, "storyboard")
    assert denied["error"]
    no_cli.assert_not_awaited()


@pytest.mark.parametrize("damage", ["id", "title", "order", "duration"])
async def test_wrong_actual_storyboard_is_not_stamped_as_matching_plan(planning_project, damage):
    project, packet = planning_project
    approved = await _approved(project)
    script = _script(approved["plan"], packet)
    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=_output_cli(project, script)):
        assert "error" not in await explainer_step(project.name, "script")
    board = _storyboard(script)
    if damage == "id":
        board["scenes"][0]["id"] = "different-scene"
    elif damage == "title":
        board["scenes"][0]["title"] = "Different editorial scene"
    elif damage == "order":
        board["scenes"].reverse()
    else:
        board["scenes"][0]["audio_duration_seconds"] = 31.0
        board["total_duration_seconds"] = 41.0
    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=_output_cli(project, script, board)):
        result = await explainer_step(project.name, "storyboard")
    assert result["error"]
    assert "storyboard" not in _stored(project)["bindings"]
    assert json.loads((project / "storyboard/storyboard.json").read_text()) == board


async def test_tampered_bound_script_blocks_storyboard_before_cli(planning_project):
    project, packet = planning_project
    approved = await _approved(project)
    script = _script(approved["plan"], packet)
    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=_output_cli(project, script)):
        assert "error" not in await explainer_step(project.name, "script")
    actual = json.loads((project / "script/script.json").read_text())
    actual["scenes"][0]["voiceover"] += " Tampered after accepted binding."
    _write(project / "script/script.json", actual)
    with patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock) as cli:
        result = await explainer_step(project.name, "storyboard")
    assert result["error"]
    cli.assert_not_awaited()
    assert (await _api(project, "show"))["bindings"]["script"]["current"] is False


async def test_concurrent_revision_during_cli_is_denied_and_first_work_joins(planning_project):
    """The actual SQLite write admission stays held through external CLI completion."""
    project, packet = planning_project
    approved = await _approved(project)
    script = _script(approved["plan"], packet)
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_cli(*args, **kwargs):
        started.set()
        await release.wait()
        _write(project / "script/script.json", script)
        return _cli_result(args)

    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=slow_cli) as cli:
        production = asyncio.create_task(explainer_step(project.name, "script"))
        try:
            await asyncio.wait_for(started.wait(), 2)
            replacement = {**approved["plan"], "thesis": "Concurrent replacement"}
            denied = await _api(project, "revise", revision=1, plan=replacement)
            assert "busy" in denied["error"]
            assert _stored(project)["revision"] == 1
        finally:
            release.set()
            result = await production
    assert "error" not in result
    assert cli.await_count == 1 and production.done()
    assert (await _api(project, "show"))["revision"] == 1


async def test_legacy_generate_step_and_refine_commands_keep_existing_contract(planning_project):
    project, _ = planning_project
    result = _cli_result(["fixture"])
    with patch("video_explainer_mcp.tools.pipeline.run_cli", return_value=result) as pipeline_cli:
        assert (await explainer_step(project.name, "script"))["success"] is True
        assert (await explainer_generate(project.name, from_step="script", to_step="storyboard"))["success"] is True
    assert [call.args for call in pipeline_cli.await_args_list] == [
        ("script", project.name),
        ("generate", project.name, "--from", "script", "--to", "storyboard", "--mock"),
    ]
    with patch("video_explainer_mcp.tools.quality.run_cli", return_value=result) as quality_cli:
        assert (await explainer_refine(project.name, "script"))["success"] is True
    quality_cli.assert_awaited_once_with(
        "refine", project.name, "--phase", "script", "--projects-dir", str(project.parent),
    )


@pytest.mark.parametrize("path", ["../outside.json", "absolute"])
async def test_storyboard_config_escape_is_denied_before_cli(planning_project, path):
    project, _ = planning_project
    await _approved(project)
    target = str(project.parent.parent / "outside.json") if path == "absolute" else path
    _write(project / "config.json", {"paths": {"storyboard": target}})
    with patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock) as cli:
        denied = await explainer_step(project.name, "script")
    assert denied["error"]
    cli.assert_not_awaited()
    assert not (project.parent.parent / "outside.json").exists()
    assert not _stored(project)["bindings"]


async def test_alternate_confined_storyboard_path_is_bound_to_exact_script(planning_project):
    project, packet = planning_project
    await _approved(project)
    _write(project / "config.json", {"paths": {"storyboard": "custom/accepted.json"}})
    script = _script(_plan(), packet)
    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=_output_cli(project, script, _storyboard(script))):
        assert "error" not in await explainer_step(project.name, "script")
        assert "error" not in await explainer_step(project.name, "storyboard")
    actual = json.loads((project / "custom/accepted.json").read_text())
    binding = (await _api(project, "show"))["bindings"]["storyboard"]
    assert binding["current"] is True and binding["path"].endswith("custom/accepted.json")
    assert actual["video_research_plan"]["parent_script_sha256"] == _stored(project)["bindings"]["script"]["sha256"]
    actual["scenes"][0]["title"] = "Tampered accepted board"
    _write(project / "custom/accepted.json", actual)
    assert (await _api(project, "show"))["bindings"]["storyboard"]["current"] is False


async def test_config_change_while_cli_awaits_denies_storyboard_binding(planning_project):
    project, packet = planning_project
    await _approved(project)
    script = _script(_plan(), packet)
    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=_output_cli(project, script)):
        assert "error" not in await explainer_step(project.name, "script")
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_cli(*args, **kwargs):
        started.set()
        await release.wait()
        _write(project / "storyboard/storyboard.json", _storyboard(script))
        return _cli_result(args)

    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=slow_cli) as cli:
        production = asyncio.create_task(explainer_step(project.name, "storyboard"))
        try:
            await asyncio.wait_for(started.wait(), 2)
            _write(project / "config.json", {"paths": {"storyboard": "changed/board.json"}})
        finally:
            release.set()
            result = await production
    assert result["error"] and "config" in result["error"].lower()
    assert cli.await_count == 1 and production.done()
    assert "storyboard" not in _stored(project)["bindings"]
    assert "video_research_plan" not in json.loads((project / "storyboard/storyboard.json").read_text())
