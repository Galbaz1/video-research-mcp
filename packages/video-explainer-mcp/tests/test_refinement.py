"""Refinement: probe-gated phases, revision-bound feedback lifecycle, exact visual frames, capped rounds."""

import asyncio
from contextlib import contextmanager
import hashlib
import json
import sqlite3

import pytest
from pydantic import ValidationError

import video_explainer_mcp.refinement as refinement
from video_explainer_mcp.models.planning import PlanRequest
from video_explainer_mcp.models.refinement import FeedbackRequest
from video_explainer_mcp.planning import apply_plan
from video_explainer_mcp.runner import SubprocessResult
from video_explainer_mcp.tools.refinement import explainer_refinement

HELP = "usage: video-explainer refine [-h] --phase {script,visual} [--projects-dir PROJECTS_DIR] project_id"
RENDER = b"fixture bytes standing in for a rendered output"
PURPOSE = "Display the observed green lamp and its source label."


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def _plan(purpose=PURPOSE):
    scenes = [{"title": f"Lamp {s}", "concept": c, "purpose": purpose if s == "a" else f"Display the observed {c} lamp.",
               "claim_ids": [f"claim-{s}"], "duration_seconds": 10.0} for s, c in (("a", "green"), ("b", "blue"))]
    return {"title": "Two lamps", "audience": "Fixture viewers", "thesis": "Show both observations.",
            "concept_order": ["green", "blue"], "scenes": scenes, "duration_budget_seconds": 30.0,
            "sources": [{"source_id": f"source-{s}", "disposition": "included", "reason": "Observation."} for s in "ab"]}


@pytest.fixture()
def project(tmp_path, monkeypatch):
    path = tmp_path / "projects" / "refine-plan"
    monkeypatch.setenv("EXPLAINER_PATH", str(tmp_path))
    monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(path.parent))
    _write(path / "config.json", {"paths": {"storyboard": "storyboard/storyboard.json"}})
    packet = {"schema_version": 1, "packet_id": "lamps", "sources": [], "claims": [], "lineage": []}
    for suffix, color in (("a", "green"), ("b", "blue")):
        text = f"The demonstration lamp {suffix} is {color}."
        digest = hashlib.sha256(text.encode()).hexdigest()
        (path / "input").mkdir(parents=True, exist_ok=True)
        (path / f"input/source-{suffix}.txt").write_text(text)
        packet["sources"].append({"id": f"source-{suffix}", "revision": "r1", "sha256": digest, "path": f"source-{suffix}.txt",
                                  "modality": "text", "asset_kind": "original", "snapshot": {"text": text, "sha256": digest},
                                  "passages": [{"id": "passage", "quote": text}]})
        packet["claims"].append({"id": f"claim-{suffix}", "text": text, "editorial_approved": True,
                                 "support": [{"source_id": f"source-{suffix}", "passage_id": "passage"}]})
    _write(path / "input/evidence-packet.json", packet)
    (path / "output").mkdir()
    (path / "output/final.mp4").write_bytes(RENDER)
    apply_plan(path.name, PlanRequest.model_validate({"action": "create", "plan": _plan()}))
    apply_plan(path.name, PlanRequest.model_validate({"action": "approve", "expected_revision": 1}))
    return path


@pytest.fixture()
def cli(monkeypatch):
    """Mock only the CLI boundary: help text and recorded argv; no process starts."""
    state = {"help": HELP, "calls": []}

    async def run_cli(*args, timeout=None, **_):
        state["calls"].append(args)
        if state["help"] is None:
            raise FileNotFoundError("Console script not found")
        return SubprocessResult(stdout=state["help"], stderr="", returncode=0, duration_seconds=0.01,
                                command=["/mock/video-explainer", *args])
    monkeypatch.setattr(refinement, "run_cli", run_cli)
    return state


async def call(project, **request):
    return await explainer_refinement(project.name, FeedbackRequest.model_validate(request))


def patch_request(revision, value="Display the green lamp with a larger source label.", expected=PURPOSE, **extra):
    return {"action": "add", "expected_revision": revision, "kind": "script", "text": "Make the label legible.",
            "scene_index": 0, "patch": {"field": "purpose", "expected": expected, "value": value}} | extra


def sources(project):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((project / "input").iterdir())}


async def test_capability_probe_derives_phases_from_cli_output(project, cli):
    probe = (await call(project, action="capabilities"))["capabilities"]
    assert (probe["status"], probe["phases"]) == ("probed", ["script", "visual"])
    assert {"--phase", "--projects-dir"} <= set(probe["flags"]) and probe["help_sha256"] == hashlib.sha256(HELP.encode()).hexdigest()
    cli["help"] = "usage: video-explainer refine [-h] project_id"
    assert (await call(project, action="capabilities"))["capabilities"]["status"] == "unparsed"
    cli["help"] = None
    probe = (await call(project, action="capabilities"))["capabilities"]
    assert (probe["status"], probe["phases"]) == ("unavailable", [])


async def test_unsupported_phase_fails_before_spend(project, cli, monkeypatch):
    produced = []

    async def produce(*args):
        produced.append(args)
    monkeypatch.setattr(refinement, "produce", produce)
    cli["help"] = HELP.replace("{script,visual}", "{script}")
    result = await call(project, action="add", expected_revision=1, kind="visual", text="x", scene_index=0,
                        processor="cli_phase", phase="visual", findings=[{"category": "legibility", "note": "small", "observed_by": "caller"}],
                        frame={"render_path": "output/final.mp4", "render_sha256": hashlib.sha256(RENDER).hexdigest(), "time_ms": 0})
    assert "refused before spend" in result["error"] and cli["calls"] == [("refine", "--help")]
    added = await call(project, action="add", expected_revision=1, kind="script", text="Tighten.", scene_index=0,
                       processor="cli_phase", phase="script")
    cli["help"] = "usage: video-explainer refine [-h] project_id"
    result = await call(project, action="apply", feedback_id=added["feedback"]["id"], processor="cli_phase")
    assert "refused before spend" in result["error"] and produced == []
    shown = (await call(project, action="show"))["feedback_items"]
    assert [(i["id"], i["attempts"]) for i in shown] == [("fb-0001", [])]


async def test_lifecycle_binds_target_revision_and_processing_result(project, cli):
    before = sources(project)
    added = (await call(project, **patch_request(1)))["feedback"]
    assert (added["status"], added["target"]["plan_revision"], added["target"]["scene_index"]) == ("open", 1, 0)
    assert (await call(project, action="show", feedback_id="fb-0001"))["feedback_items"][0]["id"] == "fb-0001"
    applied = await call(project, action="apply", feedback_id="fb-0001")
    attempt = applied["feedback"]["attempts"][0]
    assert applied["feedback"]["status"] == "applied" and applied["plan_revision"] == 2
    assert (attempt["from_revision"], attempt["to_revision"], attempt["affected_scene_indices"], attempt["unaffected_scene_indices"]) == (1, 2, [0], [1])
    assert attempt["sources_preserved"] is True and sources(project) == before
    shown = apply_plan(project.name, PlanRequest.model_validate({"action": "show"}))
    assert (shown["revision"], shown["approval_revision"]) == (2, None)
    assert shown["plan"]["scenes"][0]["purpose"] == "Display the green lamp with a larger source label."
    assert shown["plan"]["scenes"][1] == _plan()["scenes"][1]
    assert "error" in await call(project, action="apply", feedback_id="fb-0001")  # applied once only
    assert cli["calls"] == []  # local patches never call the CLI


async def test_stale_feedback_is_recorded_then_retried_on_current_revision(project, cli):
    second = _plan()["scenes"][1]["purpose"]
    await call(project, **patch_request(1))
    await call(project, **patch_request(1, value="Display only the blue lamp.", expected=second) | {"scene_index": 1})
    await call(project, action="apply", feedback_id="fb-0001")
    stale = (await call(project, action="apply", feedback_id="fb-0002"))["feedback"]
    assert stale["status"] == "stale" and stale["attempts"][0].items() >= {"status": "stale_target", "target_revision": 1, "current_revision": 2}.items()
    assert "error" in await call(project, action="retry", feedback_id="fb-0002", expected_revision=1)
    retried = (await call(project, action="retry", feedback_id="fb-0002", expected_revision=2))["feedback"]
    assert retried["status"] == "applied" and retried["rebinds"][0]["plan_revision"] == 1
    assert retried["target"]["plan_revision"] == 2 and retried["attempts"][-1]["to_revision"] == 3
    assert retried["attempts"][-1]["affected_scene_indices"] == [1]


async def test_rounds_are_capped(project, cli):
    await call(project, **patch_request(1, expected="not the current purpose", max_rounds=1))
    failed = (await call(project, action="apply", feedback_id="fb-0001"))["feedback"]
    assert failed["status"] == "failed" and "expected value" in failed["attempts"][0]["error"]
    result = await call(project, action="retry", feedback_id="fb-0001", expected_revision=1)
    assert "round cap" in result["error"]
    assert len((await call(project, action="show"))["feedback_items"][0]["attempts"]) == 1


async def test_visual_review_binds_exact_render_frame(project, cli):
    frame = {"render_path": "output/final.mp4", "render_sha256": hashlib.sha256(RENDER).hexdigest(), "time_ms": 1250, "frame_index": 37}
    findings = [{"category": "legibility", "note": "Source label too small at 1.25 s.", "observed_by": "caller"},
                {"category": "incorrect_visual", "note": "Lamp drawn blue.", "observed_by": "model"}]
    result = await call(project, **patch_request(1) | {"kind": "visual", "frame": frame, "findings": findings})
    record = result["feedback"]
    assert record["target"]["frame"]["render_sha256"] == frame["render_sha256"] and record["target"]["frame"]["time_ms"] == 1250
    assert record["target"]["frame"]["frame_time_within_duration"].startswith("UNKNOWN")
    assert [f["verified"] for f in record["findings"]] == [False, False] and result["watched_by_tool"] is False
    wrong = await call(project, **patch_request(1) | {"kind": "visual", "frame": frame | {"render_sha256": "0" * 64}, "findings": findings})
    assert "unseen output" in wrong["error"]
    assert len((await call(project, action="show"))["feedback_items"]) == 1
    with pytest.raises(ValidationError):
        FeedbackRequest.model_validate(patch_request(1) | {"kind": "visual", "findings": findings})


async def test_cli_phase_records_processing_result(project, cli, monkeypatch):
    async def produce(project_path, connection, state, argv, run_cli):
        state["bindings"]["script"] = {"sha256": "1" * 64, "plan_revision": state["revision"]}
        return SubprocessResult(stdout="refined", stderr="", returncode=0, duration_seconds=0.1, command=["/mock/video-explainer", *argv])
    monkeypatch.setattr(refinement, "produce", produce)
    await call(project, action="add", expected_revision=1, kind="script", text="Tighten.", scene_index=0, processor="cli_phase", phase="script")
    record = (await call(project, action="apply", feedback_id="fb-0001", processor="cli_phase"))["feedback"]
    attempt = record["attempts"][0]
    assert record["status"] == "applied" and attempt["changed_bindings"] == ["script"]
    assert attempt["command"][1:5] == ["refine", "refine-plan", "--phase", "script"] and "--projects-dir" in attempt["command"]
    assert attempt["refinement_quality"].startswith("UNKNOWN")

    async def failing(*args):
        raise RuntimeError("cli exited 2")
    monkeypatch.setattr(refinement, "produce", failing)
    await call(project, action="add", expected_revision=1, kind="script", text="Again.", scene_index=1, processor="cli_phase", phase="script")
    failed = (await call(project, action="apply", feedback_id="fb-0002", processor="cli_phase"))["feedback"]
    assert failed["status"] == "failed" and "cli exited 2" in failed["attempts"][0]["error"]


async def test_feedback_requires_managed_plan(project, cli):
    (project / "planning.sqlite3").unlink()
    assert "managed video plan" in (await call(project, **patch_request(0)))["error"]


async def test_same_revision_replaced_artifact_requires_feedback_rebind(project, cli, monkeypatch):
    from video_explainer_mcp.planning import plan_transaction, save_plan

    with plan_transaction(project) as (connection, state):
        state["bindings"]["script"] = {"sha256": "1" * 64}
        save_plan(connection, state)
    await call(project, action="add", expected_revision=1, kind="script", text="Tighten.",
               scene_index=0, processor="cli_phase", phase="script")
    with plan_transaction(project) as (connection, state):
        state["bindings"]["script"] = {"sha256": "2" * 64}
        save_plan(connection, state)
    dispatched = []

    async def produce(*args):
        dispatched.append(args)
        raise RuntimeError("Refinement must not run against replacement script")

    monkeypatch.setattr(refinement, "produce", produce)
    result = await call(project, action="apply", feedback_id="fb-0001", processor="cli_phase")
    assert result["feedback"]["status"] == "stale" and dispatched == []
    assert result["feedback"]["target"]["bindings"] == {"script": "1" * 64}


async def test_cancelled_cli_attempt_remains_counted_after_reopen(project, monkeypatch):
    started = asyncio.Event()
    dispatched = []

    async def run_cli(*args, **kwargs):
        if args == ("refine", "--help"):
            return SubprocessResult(stdout=HELP, stderr="", returncode=0, duration_seconds=0,
                                    command=["/mock/video-explainer", *args])
        dispatched.append(args)
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(refinement, "run_cli", run_cli)
    await call(project, action="add", expected_revision=1, kind="script", text="Tighten.",
               scene_index=0, processor="cli_phase", phase="script", max_rounds=1)
    task = asyncio.create_task(call(project, action="apply", feedback_id="fb-0001", processor="cli_phase"))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    record = (await call(project, action="show", feedback_id="fb-0001"))["feedback_items"][0]
    assert record["status"] == "failed" and len(record["attempts"]) == 1
    assert record["attempts"][0]["status"] == "cancelled_unknown"
    result = await call(project, action="retry", feedback_id="fb-0001", processor="cli_phase", expected_revision=1)
    assert "round cap" in result["error"] and len(dispatched) == 1


async def test_replaced_visual_render_requires_feedback_rebind(project):
    frame = {"render_path": "output/final.mp4", "render_sha256": hashlib.sha256(RENDER).hexdigest(), "time_ms": 1250}
    await call(project, **patch_request(1) | {"kind": "visual", "frame": frame,
               "findings": [{"category": "legibility", "note": "Small source label.", "observed_by": "caller"}]})
    (project / "output/final.mp4").write_bytes(b"replacement render")
    result = await call(project, action="apply", feedback_id="fb-0001")
    assert result["feedback"]["status"] == "stale" and result["plan_revision"] == 1


@pytest.mark.parametrize("failure", ["save", "commit"])
async def test_cancelled_cli_preserves_cancellation_when_persistence_fails(project, monkeypatch, failure):
    started = asyncio.Event()

    def fail(*args):
        raise sqlite3.OperationalError("controlled persistence failure")

    class Connection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def commit(self):
            fail()

    original = refinement.production_transaction

    @contextmanager
    def transaction(project_id):
        with original(project_id) as (path, connection, state):
            yield path, Connection(connection) if failure == "commit" else connection, state

    async def run_cli(*args, **kwargs):
        if args == ("refine", "--help"):
            return SubprocessResult(stdout=HELP, stderr="", returncode=0, duration_seconds=0,
                                    command=["/mock/video-explainer", *args])
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            if failure == "save":
                monkeypatch.setattr(refinement, "_save", fail)

    monkeypatch.setattr(refinement, "run_cli", run_cli)
    monkeypatch.setattr(refinement, "production_transaction", transaction)
    await call(project, action="add", expected_revision=1, kind="script", text="Tighten.",
               scene_index=0, processor="cli_phase", phase="script")
    task = asyncio.create_task(call(project, action="apply", feedback_id="fb-0001", processor="cli_phase"))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError) as caught:
        await task
    assert any("persistence liability: OperationalError" in note for note in caught.value.__notes__)
