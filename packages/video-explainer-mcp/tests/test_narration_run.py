"""Real bound-script admission and durable owned audio runs with no paid requests."""

import asyncio
import hashlib
import json
import os

from pydantic import ValidationError
import pytest

from video_explainer_mcp.models.narration import NarrationRequest
from video_explainer_mcp.models.planning import PlanRequest
from video_explainer_mcp import narration_pcm as pcm
from video_explainer_mcp import narration_run as runs
from video_explainer_mcp.narration_provider import ProviderError
from video_explainer_mcp.plan_artifacts import bind_script, require_binding
from video_explainer_mcp.planning import apply_plan, plan_transaction, save_plan


@pytest.fixture
def approved(tmp_path, monkeypatch):
    """Bind a manually prepared two-sentence script to a real approved source/plan."""
    project = tmp_path / "projects" / "narration"
    inputs = project / "input"
    inputs.mkdir(parents=True)
    monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(project.parent))
    monkeypatch.setenv("EXPLAINER_TTS_PROVIDER", "mock")
    text = "One. Two."
    sha = hashlib.sha256(text.encode()).hexdigest()
    (inputs / "source.txt").write_text(text)
    packet = {"schema_version": 1, "packet_id": "owned-narration", "sources": [{"id": "source",
              "revision": "r1", "sha256": sha, "path": "source.txt", "modality": "text", "asset_kind": "original",
              "snapshot": {"text": text, "sha256": sha}, "passages": [{"id": "passage", "quote": text}]}],
              "claims": [{"id": "claim", "text": text, "editorial_approved": True,
                          "support": [{"source_id": "source", "passage_id": "passage"}]}], "lineage": []}
    (inputs / "evidence-packet.json").write_text(json.dumps(packet))
    plan = {"title": "Measured tones", "audience": "Fixture readers", "thesis": "Measure a declared synthetic performance.",
            "concept_order": ["one"], "scenes": [{"title": "Two events", "concept": "one", "purpose": "Show declared tone events.",
            "claim_ids": ["claim"], "duration_seconds": 2.0}], "sources": [{"source_id": "source", "disposition": "included", "reason": "Exact supplied source."}],
            "duration_budget_seconds": 2.0}
    apply_plan(project.name, PlanRequest(action="create", expected_revision=0, plan=plan))
    apply_plan(project.name, PlanRequest(action="approve", expected_revision=1))
    script = {"title": plan["title"], "total_duration_seconds": 2.0, "scenes": [{"scene_id": "first", "title": "Two events",
              "voiceover": text, "visual_cue": {"description": "Show declared tone events."}, "duration_seconds": 2.0}]}
    (project / "script").mkdir()
    (project / "script/script.json").write_text(json.dumps(script))
    with plan_transaction(project) as (connection, state):
        bind_script(project, state, packet)
        save_plan(connection, state)
        script = require_binding(project, state, "script")
    return project, state, script


def read_receipt(project, result):
    return json.loads((project / result["receipt"]["path"]).read_text())


async def test_full_mock_receipt_preserves_transcript_and_measured_sample_timing(approved):
    project, state, script = approved
    original = (project / "script/script.json").read_bytes()
    result = await runs.produce_narration(project, state, script, NarrationRequest())
    assert result["success"] and result["status"] == "accepted"
    assert result["artifact"]["frames"] == 14400 and result["artifact"]["duration_seconds"] == 0.6
    assert "".join(row["text"] for row in result["sentences"]) == result["transcript"] == "One. Two."
    assert [(r["start_seconds"], r["audio_end_seconds"]) for r in result["sentences"]] == [(0, 0.2), (0.3, 0.5)]
    assert [(w["start_seconds"], w["end_seconds"]) for w in result["words"]] == [(0, 0.2), (0.3, 0.5)]
    assert [(w["text_begin"], w["text_end"]) for w in result["words"]] == [(0, 4), (5, 9)]
    assert result["binding"]["audio_path"] == result["artifact"]["path"]
    assert not result["artifact"]["path"].startswith("/")
    assert result["binding"]["parent_script_sha256"] == state["bindings"]["script"]["sha256"]
    assert result["video_research_plan"]["visual_audio_semantics"] == "not_verified"
    assert read_receipt(project, result)["artifact"] == result["artifact"]
    assert (project / "script/script.json").read_bytes() == original
    assert "tone" in result["word_alignment"] and result["renderer_consumption"] == "unverified"


@pytest.mark.parametrize("text", ["  One.\n Two!  ", "第一句。第二句！", 'One. "Two?"', "A 3.14 value. Then two."])
def test_sentence_partition_never_edits_approved_text(text):
    assert "".join(runs.split_sentences(text)) == text


async def test_preview_cache_requires_exact_configuration_and_audio_bytes(approved, monkeypatch):
    project, state, script = approved
    original, calls = runs.synthesize, []
    async def counted(text, selected, returned):
        calls.append(text)
        return await original(text, selected, returned)
    monkeypatch.setattr(runs, "synthesize", counted)
    request = NarrationRequest(action="preview")
    first = await runs.produce_narration(project, state, script, request)
    again = await runs.produce_narration(project, state, script, request)
    assert first["success"] and again["cache_hit"] and len(calls) == 2
    faster = await runs.produce_narration(project, state, script, NarrationRequest(action="preview", rate=2))
    assert faster["success"] and not faster["cache_hit"] and faster["artifact"]["frames"] == 9600
    assert faster["cache_key"] != first["cache_key"] and len(calls) == 4
    paused = await runs.produce_narration(project, state, script, NarrationRequest(action="preview", pause_seconds=0.2))
    assert paused["success"] and paused["artifact"]["frames"] == 19200 and len(calls) == 6
    changed_region = await runs.produce_narration(project, state, script, NarrationRequest(action="preview", region="cn"))
    assert changed_region["success"] and changed_region["cache_key"] != first["cache_key"]
    (project / first["artifact"]["path"]).write_bytes(pcm.tone("corrupted cache", 1)[0])
    refused = await runs.produce_narration(project, state, script, request)
    assert not refused["success"] and refused["reason"] == "admission_or_cache_refused"
    assert len(calls) == 8


async def test_missing_preview_scene_and_tampered_source_fail_before_synthesis(approved, monkeypatch):
    project, state, script = approved
    monkeypatch.setattr(runs, "synthesize", lambda *a: pytest.fail("unauthorized synthesis"))
    missing = await runs.produce_narration(project, state, script, NarrationRequest(action="preview", scene_id="missing"))
    assert not missing["success"] and not (project / ".narration").exists()
    (project / "input/source.txt").write_text("Changed source.")
    refused = await runs.produce_narration(project, state, script, NarrationRequest())
    assert not refused["success"] and not (project / ".narration").exists()


async def test_bound_script_is_rechecked_before_promotion(approved, monkeypatch):
    project, state, script = approved
    original = runs.synthesize
    async def tampering(text, selected, returned):
        outcome = await original(text, selected, returned)
        (project / "script/script.json").write_text("{}")
        return outcome
    monkeypatch.setattr(runs, "synthesize", tampering)
    result = await runs.produce_narration(project, state, script, NarrationRequest())
    assert not result["success"] and result["artifact"] is None
    assert not list((project / ".narration").glob("*/narration.wav"))
    assert [r["status"] for r in result["sentences"]] == ["accepted", "accepted"]


async def test_partial_failure_and_unknown_same_key_do_not_regenerate(approved, monkeypatch):
    project, state, script = approved
    original, calls = runs.synthesize, []
    async def partial(text, selected, returned):
        calls.append(text)
        if len(calls) == 2:
            raise ProviderError("provider_request_outcome_unknown", "unknown")
        return await original(text, selected, returned)
    monkeypatch.setattr(runs, "synthesize", partial)
    result = await runs.produce_narration(project, state, script, NarrationRequest())
    assert result["status"] == "unknown" and not result["success"] and result["artifact"] is None
    assert [r["status"] for r in result["sentences"]] == ["accepted", "unknown"]
    assert (project / result["sentences"][0]["artifact"]["path"]).is_file()
    repeated = await runs.produce_narration(project, state, script, NarrationRequest())
    assert not repeated["success"] and "regeneration_refused" in repeated["reason"] and len(calls) == 2


async def test_failed_first_sentence_leaves_required_rest_unrun(approved, monkeypatch):
    project, state, script = approved
    async def failed(*args):
        raise ProviderError("provider_business_status", "failed", 1004)
    monkeypatch.setattr(runs, "synthesize", failed)
    result = await runs.produce_narration(project, state, script, NarrationRequest())
    assert [r["status"] for r in result["sentences"]] == ["failed", "unrun"]
    assert result["provider_status"] == 1004 and result["artifact"] is None


async def test_dispatch_receipt_precedes_post_and_cancel_retains_unknown(approved, monkeypatch):
    project, state, script = approved
    for key, value in {"EXPLAINER_NARRATION_MINIMAX_ENABLED": "1", "EXPLAINER_NARRATION_MINIMAX_VOICES": "fixture-voice",
                       "EXPLAINER_NARRATION_MINIMAX_DOWNLOAD_HOSTS": "audio.provider.invalid", "MINIMAX_API_KEY": "fixture-private-key"}.items():
        monkeypatch.setenv(key, value)
    entered, calls = asyncio.Event(), []
    async def waiting(text, selected, returned):
        calls.append(text)
        receipts = list((project / ".narration").glob("*/receipt.json"))
        assert json.loads(receipts[0].read_text())["sentences"][0]["status"] == "dispatching"
        entered.set()
        await asyncio.Future()
    monkeypatch.setattr(runs, "synthesize", waiting)
    request = NarrationRequest(provider="minimax", model="speech-2.8-hd", voice="fixture-voice")
    task = asyncio.create_task(runs.produce_narration(project, state, script, request))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    receipt = json.loads(next((project / ".narration").glob("*/receipt.json")).read_text())
    assert receipt["status"] == "unknown" and receipt["artifact"] is None
    assert [r["status"] for r in receipt["sentences"]] == ["unknown", "unrun"]
    repeated = await runs.produce_narration(project, state, script, request)
    assert not repeated["success"] and len(calls) == 1
    assert "fixture-private-key" not in json.dumps(receipt)


async def test_custom_audio_measured_contained_and_missing_alignment_disclosed(approved):
    project, state, script = approved
    path = project / "custom.wav"
    path.write_bytes(pcm.tone("One. Two.", 1)[0])
    result = await runs.produce_narration(project, state, script, NarrationRequest(action="custom", custom_audio="custom.wav"))
    assert result["success"] and result["artifact"]["frames"] == 9600
    assert result["transcript"] == "One. Two." and result["words"] is None and result["word_alignment"] == "absent"
    assert result["sentences"][0]["scene_timing"] == "absent_custom_audio"
    assert result["sentences"][0]["pause_frames"] == 0
    assert path.read_bytes() == pcm.tone("One. Two.", 1)[0]


@pytest.mark.parametrize("kind", ["traversal", "absolute", "symlink", "fifo"])
async def test_custom_path_bypass_never_produces_audio(approved, kind):
    project, state, script = approved
    path = project / "custom.wav"
    path.write_bytes(pcm.tone("One.", 1)[0])
    selected = "../outside.wav" if kind == "traversal" else str(path) if kind == "absolute" else "link.wav"
    if kind == "symlink":
        (project / selected).symlink_to(path)
    elif kind == "fifo":
        os.mkfifo(project / selected)
    result = await runs.produce_narration(project, state, script, NarrationRequest(action="custom", custom_audio=selected))
    assert not result["success"] and not (project / ".narration").exists()


async def test_custom_mutation_and_over_budget_do_not_promote(approved, monkeypatch):
    project, state, script = approved
    path = project / "custom.wav"
    path.write_bytes(pcm.tone("One.", 1)[0])
    original, calls = runs.snapshot, []
    def changed(candidate):
        body = original(candidate)
        if candidate == path:
            calls.append(True)
            if len(calls) == 1:
                path.write_bytes(pcm.tone("changed words", 1)[0])
        return body
    monkeypatch.setattr(runs, "snapshot", changed)
    result = await runs.produce_narration(project, state, script, NarrationRequest(action="custom", custom_audio="custom.wav"))
    assert not result["success"] and result["artifact"] is None
    monkeypatch.setattr(runs, "snapshot", original)
    over = await runs.produce_narration(project, state, script, NarrationRequest(pause_seconds=2))
    assert not over["success"] and over["artifact"] is None
    assert not list((project / ".narration").glob("*/narration.wav"))
    with pytest.raises(ValidationError):
        NarrationRequest(action="custom", custom_audio="custom.wav", rate=1.5)
