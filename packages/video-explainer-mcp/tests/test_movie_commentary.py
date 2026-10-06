"""C1/C2: fixed-source durable project and plan validation before immutable shards."""

from __future__ import annotations

import json

from tests.test_movie_commentary_support import (
    approval, author, env as env, frozen, prepare, segment, sha,
)
from video_explainer_mcp.tools.commentary import (
    commentary_approve_shard, commentary_freeze_shards, commentary_inspect, commentary_prepare,
    commentary_validate_plan,
)


async def test_prepare_binds_source_hash_and_pinned_ffprobe_receipt(env):
    """GIVEN a fixed source WHEN prepared THEN bytes, probe argv/output and facts are durable."""
    result = await prepare(env)
    assert result["source"]["sha256"] == sha(env["source"].read_bytes())
    assert result["source_state"] == "current" and result["recommended_stage"] == "analyze_source"
    manifest = json.loads((env["root"] / "project.json").read_text())
    (command,) = env["state"]["calls"]
    assert command[0] == "/pinned/ffprobe" and command[-1] == str(env["source"])
    assert manifest["probe"]["command"] == command and manifest["probe"]["ffprobe"]["sha256"] == "1" * 64
    assert manifest["probe"]["facts"]["duration_sec"] == 120.0
    facts = json.loads((env["root"] / "plan/execution_facts.json").read_text())
    assert facts["source_cut_max_sec"] == 120.0 and facts["source_cut_basis"] == "probed_duration"
    assert manifest["media_authority"] == "not_inferred_requires_per_shard_approval"


async def test_prepare_refuses_wrong_source_revision_existing_project_and_bad_ceiling(env):
    wrong = await commentary_prepare(project_id="film", source_path=str(env["source"]),
                                     expected_source_sha256="0" * 64)
    assert "differs from the expected revision" in wrong["error"] and not env["root"].exists()
    ceiling = await prepare(env, source_cut_max_sec=500.0)
    assert "within the probed duration" in ceiling["error"] and not env["root"].exists()
    await prepare(env)
    again = await prepare(env)
    assert "already exists" in again["error"]


async def test_plan_errors_are_all_reported_and_block_freezing(env):
    await prepare(env, source_cut_max_sec=30.0)
    bad = [segment(1, segment_id="SEG_0009"), segment(2, narration={"text": "  "}),
           segment(3, visual_plan={"rough_interval_sec": [25, 40],
                                   "movie_locator": {"evidence_refs": ["../project.json", "/etc/hosts"]}}),
           segment(4, audio_plan={"source_audio_mode": "original", "bgm_mode": "licensed"})]
    author(env, 4, segments=bad, script="SEG_0001\nsomething else\n", source_sha="f" * 64)
    (env["root"] / "plan/watch_notes/n4.md").unlink()
    (env["root"] / "plan/watch_notes/n1.md").unlink()
    (env["root"] / "plan/watch_notes/n1.md").symlink_to(env["root"] / "project.json")
    result = await commentary_validate_plan(project_id="film")
    text = "\n".join(result["errors"])
    for expected in ["source_sha256 differs", "segment_id must be SEG_0001", "SEG_0002: narration.text is required",
                     "exceeds source_cut_max_sec", "unsafe evidence ref: ../project.json",
                     "unsafe evidence ref: /etc/hosts", "SEG_0004: evidence does not exist",
                     "unsafe evidence ref: plan/watch_notes/n1.md", "source_audio_mode must be ducked_bed or muted",
                     "licensed BGM requires a bgm_manifest", "SEG_0001: narration_script.md does not preserve"]:
        assert expected in text, expected
    assert result["valid"] is False and "plan_sha256" not in result
    refused = await commentary_freeze_shards(project_id="film")
    assert "Plan validation failed" in refused["error"] and list((env["root"] / "shards").iterdir()) == []


async def test_valid_plan_freezes_immutable_content_addressed_shards(env):
    result = await frozen(env, count=3, per_shard=2)
    assert list(result["shards"]) == ["shard_01", "shard_02"] and result["segment_count"] == 3
    shard_dir = env["root"] / "shards" / result["set_id"]
    first = json.loads((shard_dir / "shard_01.json").read_text())
    assert [s["segment_id"] for s in first["segments"]] == ["SEG_0001", "SEG_0002"]
    assert first["segments"][0] == segment(1) and first["source"]["sha256"] == sha(env["source"].read_bytes())
    assert set(first["evidence"]) == {"plan/watch_notes/n1.md", "plan/watch_notes/n2.md"}
    again = await commentary_freeze_shards(project_id="film", segments_per_shard=2)
    assert again == result
    regrouped = await commentary_freeze_shards(project_id="film", segments_per_shard=1)
    assert "Immutable record differs" in regrouped["error"]
    assert sorted(p.name for p in shard_dir.iterdir()) == ["index.json", "shard_01.json", "shard_02.json"]


async def test_changed_plan_evidence_or_source_have_no_current_frozen_set(env):
    result = await frozen(env)
    state = await commentary_inspect(project_id="film")
    assert state["frozen_shard_sets"] == [result["set_id"]]
    note = env["root"] / "plan/watch_notes/n2.md"
    note.write_text("edited note\n")
    refused = await commentary_approve_shard(project_id="film", shard_id="shard_01",
                                             approval=approval(env, result["shards"]["shard_01"]))
    assert "no frozen shard set" in refused["error"]
    note.write_text("Caller watch note 2.\n")
    env["source"].write_bytes(b"changed source bytes")
    changed = await commentary_approve_shard(project_id="film", shard_id="shard_01",
                                             approval=approval(env, result["shards"]["shard_01"]))
    assert "Source movie bytes changed" in changed["error"]
    assert (await commentary_inspect(project_id="film"))["recommended_stage"] == "blocked_source_changed"
