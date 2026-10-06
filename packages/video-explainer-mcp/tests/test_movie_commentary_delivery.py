"""C3/C4: explicit shard approval, delivery refusal and mocked concat/decode/timing."""

from __future__ import annotations

import json
from pathlib import Path

from tests.test_movie_commentary_support import approval, env as env, execute, frozen
from video_explainer_mcp.tools.commentary import (
    commentary_approve_shard, commentary_assemble, commentary_validate_delivery,
)


async def test_approval_scope_is_exact_immutable_and_executes_nothing(env):
    result = await frozen(env)
    digest = result["shards"]["shard_01"]
    wrong_shard = await commentary_approve_shard(project_id="film", shard_id="shard_01",
                                                 approval=approval(env, result["shards"]["shard_02"]))
    assert "different shard bytes" in wrong_shard["error"]
    wrong_source = await commentary_approve_shard(project_id="film", shard_id="shard_01",
                                                  approval=approval(env, digest, source_sha256="0" * 64))
    assert "different source revision" in wrong_source["error"]
    scope = await commentary_approve_shard(project_id="film", shard_id="shard_01", approval=approval(env, digest))
    assert scope["status"] == "approved_scope_recorded" and scope["agents_spawned"] == 0
    assert scope["renders_started"] == 0 and len(env["state"]["calls"]) == 1  # only the prepare probe
    record = json.loads((env["root"] / "approvals" / result["set_id"] / "shard_01.json").read_text())
    assert record["rights_inferred"] is False and record["authority_basis"] == "caller_asserted_not_verified"
    same = await commentary_approve_shard(project_id="film", shard_id="shard_01", approval=approval(env, digest))
    assert same["approval_sha256"] == scope["approval_sha256"]
    other = await commentary_approve_shard(project_id="film", shard_id="shard_01",
                                           approval=approval(env, digest, approved_by="someone else"))
    assert "Immutable record differs" in other["error"]


async def test_missing_approval_mp4_or_report_refuses_delivery(env):
    result = await frozen(env)
    await execute(env, result, "shard_01")
    missing = await commentary_validate_delivery(project_id="film")
    assert missing["valid"] is False
    assert any("shard_02: no explicit execution approval" in e for e in missing["errors"])
    await commentary_approve_shard(project_id="film", shard_id="shard_02",
                                   approval=approval(env, result["shards"]["shard_02"]))
    no_mp4 = await commentary_validate_delivery(project_id="film")
    assert any("shard_02: missing execution MP4 or report" in e for e in no_mp4["errors"])
    refused = await commentary_assemble(project_id="film")
    assert "Shards are not deliverable" in refused["error"] and len(env["state"]["calls"]) == 1


async def test_report_must_match_frozen_shard_bytes_and_pass_qa(env):
    result = await frozen(env)
    await execute(env, result, "shard_01", segments=[{"segment_id": "SEG_0002", "status": "resolved",
                                                     "understanding_mode": "grounded"}])
    scope = await execute(env, result, "shard_02", qa_checks={"decode": False}, unresolved=["seam"])
    Path(scope["output_video"]).write_bytes(b"replaced after the report")
    errors = "\n".join((await commentary_validate_delivery(project_id="film"))["errors"])
    for expected in ["shard_01: report segments differ from the frozen shard",
                     "shard_02: shard QA checks are missing or failed", "shard_02: report lists unresolved items",
                     "shard_02: report output_video differs from the current MP4 bytes"]:
        assert expected in errors, expected


async def test_valid_shards_assemble_with_full_decode_timing_and_deliver(env):
    result = await frozen(env)
    for shard_id in result["shards"]:
        await execute(env, result, shard_id)
    qa = await commentary_assemble(project_id="film", tolerance_sec=0.1)
    concat, decode, probe = env["state"]["calls"][1:]
    assert concat[0] == "/pinned/ffmpeg" and "concat" in concat and concat[-1].endswith("full/commentary.mp4")
    assert decode[-3:] == ["-f", "null", "-"] and "-xerror" in decode and probe[0] == "/pinned/ffprobe"
    assert qa["overall_pass"] is True and qa["timing"]["expected_duration_sec"] == 4.0
    assert [s["shard_id"] for s in qa["shards"]] == ["shard_01", "shard_02"]
    delivered = await commentary_validate_delivery(project_id="film")
    assert delivered["valid"] is True and delivered["errors"] == []
    assert delivered["native_qualification"] == "requires_actual_ffmpeg_receipts_in_qa"
    again = await commentary_assemble(project_id="film")
    assert "already exists" in again["error"]


async def test_timing_mismatch_or_decode_failure_cannot_deliver(env):
    result = await frozen(env)
    for shard_id in result["shards"]:
        await execute(env, result, shard_id)
    env["state"]["decode_error"] = "Media process exited with status 1: corrupt packet"
    failed = await commentary_assemble(project_id="film")
    assert "corrupt packet" in failed["error"]
    assert not (env["root"] / "full/commentary.mp4").exists() and not (env["root"] / "full/qa.json").exists()
    env["state"]["decode_error"], env["state"]["final_duration"] = None, 9.0
    qa = await commentary_assemble(project_id="film")
    assert qa["checks"]["timing"] is False and qa["overall_pass"] is False
    assert "did not pass full decode and timing" in "\n".join(
        (await commentary_validate_delivery(project_id="film"))["errors"])


async def test_changes_after_assembly_refuse_delivery(env):
    result = await frozen(env)
    scopes = [await execute(env, result, shard_id) for shard_id in result["shards"]]
    await commentary_assemble(project_id="film")
    (env["root"] / "full/commentary.mp4").write_bytes(b"swapped final")
    assert "final MP4 bytes differ" in "\n".join((await commentary_validate_delivery(project_id="film"))["errors"])
    Path(scopes[0]["shard_path"]).write_text("{}")
    changed = await commentary_validate_delivery(project_id="film")
    assert changed["valid"] is False and "changed after freezing" in changed["errors"][0]
