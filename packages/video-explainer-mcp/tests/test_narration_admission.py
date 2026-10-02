"""Real plan transactions and byte admission for owned measured narration."""

import asyncio
import hashlib
import json
from unittest.mock import AsyncMock, patch

import pytest

from .test_planning import _api, _approved, _script, _stored, _write
from .test_planning import planning_project as _planning_project
from video_explainer_mcp.models.narration import NarrationRequest
from video_explainer_mcp.plan_artifacts import bind_script, require_binding
from video_explainer_mcp.planning import plan_transaction, require_approved, save_plan
from video_explainer_mcp.tools.audio import explainer_narration

planning_project = _planning_project


async def bound_script(project, packet):
    """Use current source-exact approval and production binding in a real database."""
    approved = await _approved(project)
    _write(project / "script/script.json", _script(approved["plan"], packet))
    with plan_transaction(project) as (connection, state):
        bind_script(project, state, require_approved(project, state))
        save_plan(connection, state)
    return _stored(project)


async def test_narration_requires_managed_current_script_before_backend(planning_project):
    project, _ = planning_project
    with patch("video_explainer_mcp.narration_run.produce_narration", new_callable=AsyncMock) as backend:
        result = await explainer_narration(project.name, NarrationRequest())
    assert "managed plan" in result["error"]
    backend.assert_not_awaited()


async def test_measured_narration_promotes_exact_child_audio_and_keeps_script(planning_project):
    project, packet = planning_project
    before = await bound_script(project, packet)
    original_script = (project / "script/script.json").read_bytes()
    result = await explainer_narration(project.name, NarrationRequest())
    assert result["success"] and not result["factual_success"]
    after = _stored(project)
    binding = after["bindings"]["narration"]
    assert binding["parent_script_sha256"] == before["bindings"]["script"]["sha256"]
    assert (project / "script/script.json").read_bytes() == original_script
    assert hashlib.sha256((project / binding["audio_path"]).read_bytes()).hexdigest() == binding["audio_sha256"]
    body = require_binding(project, after, "narration")
    assert body["artifact"]["duration_seconds"] > 0
    assert body["video_research_plan"]["source_commitment_sha256"] == before["source_commitment_sha256"]


async def test_narration_binding_refuses_audio_changed_after_promotion(planning_project):
    project, packet = planning_project
    await bound_script(project, packet)
    assert (await explainer_narration(project.name, NarrationRequest()))["success"]
    state = _stored(project)
    (project / state["bindings"]["narration"]["audio_path"]).write_bytes(b"broken audio")
    with pytest.raises(ValueError, match="audio bytes changed"):
        require_binding(project, state, "narration")


async def test_narration_binding_rejects_modified_script_parent(planning_project):
    project, packet = planning_project
    await bound_script(project, packet)
    assert (await explainer_narration(project.name, NarrationRequest()))["success"]
    path = project / "script/script.json"
    script = json.loads(path.read_text())
    script["scenes"][0]["voiceover"] = "A changed narrative claim."
    _write(path, script)
    with pytest.raises(ValueError, match="Bound script bytes"):
        require_binding(project, _stored(project), "narration")


async def test_current_source_change_refuses_even_cached_narration(planning_project):
    project, packet = planning_project
    await bound_script(project, packet)
    assert (await explainer_narration(project.name, NarrationRequest()))["success"]
    (project / "input/source-a.txt").write_text("A changed original source.")
    with patch("video_explainer_mcp.narration_run.produce_narration", new_callable=AsyncMock) as backend:
        result = await explainer_narration(project.name, NarrationRequest())
    assert "original source hash mismatch" in result["error"]
    backend.assert_not_awaited()


async def test_narration_keeps_revision_lock_through_async_production(planning_project):
    from video_explainer_mcp.narration_run import produce_narration

    project, packet = planning_project
    state = await bound_script(project, packet)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(*args):
        entered.set()
        await release.wait()
        return await produce_narration(*args)

    with patch("video_explainer_mcp.narration_run.produce_narration", side_effect=slow):
        task = asyncio.create_task(explainer_narration(project.name, NarrationRequest()))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            denied = await _api(project, "revise", revision=1, plan=state["plan"])
            assert "busy" in denied["error"]
        finally:
            release.set()
            result = await task
    assert result["success"] and _stored(project)["revision"] == 1


async def test_failed_sentence_result_is_retained_without_database_promotion(planning_project):
    project, packet = planning_project
    before = await bound_script(project, packet)
    failed = {"success": False, "status": "failed", "sentences": [
        {"text": "Required sentence.", "status": "failed"},
        {"text": "Unrun sentence.", "status": "unrun"},
    ]}
    with patch("video_explainer_mcp.narration_run.produce_narration", new=AsyncMock(return_value=failed)):
        result = await explainer_narration(project.name, NarrationRequest())
    assert not result["success"] and result["sentences"] == failed["sentences"]
    assert _stored(project) == before and "narration" not in before["bindings"]


@pytest.mark.parametrize("action", ["generate", "preview"])
async def test_cached_receipt_corruption_cannot_replace_trusted_binding(planning_project, action):
    """Keep WAV bytes exact while corrupting receipt text/status/timing."""
    project, packet = planning_project
    await bound_script(project, packet)
    first = await explainer_narration(project.name, NarrationRequest(action=action))
    assert first["success"]
    before = _stored(project)
    path = project / first["receipt"]["path"]
    receipt = json.loads(path.read_text())
    receipt["sentences"][0].update(text="Altered sentence.", status="failed")
    receipt["words"][0].update(start_frame=-200, end_frame=999999)
    _write(path, receipt)
    with patch("video_explainer_mcp.narration_run.synthesize", new_callable=AsyncMock) as backend:
        refused = await explainer_narration(project.name, NarrationRequest(action=action))
    assert not refused["success"]
    backend.assert_not_awaited()
    assert _stored(project) == before
