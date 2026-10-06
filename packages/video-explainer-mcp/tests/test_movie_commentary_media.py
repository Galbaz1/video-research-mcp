"""Decoder command contracts; all media processes remain mocked."""

import json
from pathlib import Path

import pytest

from tests.test_movie_commentary_support import env as env, execute, frozen, prepare, sha
from video_explainer_mcp.commentary import delivery, project
from video_explainer_mcp.tools.commentary import commentary_assemble


async def test_movie_probe_allows_direct_containers_and_only_local_files(env):
    await prepare(env)
    command = env["state"]["calls"][0]
    assert command[command.index("-protocol_whitelist") + 1] == "file"
    formats = set(command[command.index("-format_whitelist") + 1].split(","))
    assert {"mov", "matroska", "webm", "avi", "mpeg", "mpegts", "ogg", "asf", "flv"} <= formats
    assert not formats & {"concat", "hls", "dash", "sdp", "image2", "webm_dash_manifest"}
    assert command.index("-format_whitelist") < len(command) - 1


async def test_concat_children_and_final_are_fixed_mov_with_local_protocol(env):
    result = await frozen(env)
    for shard_id in result["shards"]:
        await execute(env, result, shard_id)
    qa = await commentary_assemble(project_id="film")
    concat, decode, probe = env["state"]["calls"][1:]
    assert qa["overall_pass"] is True
    assert concat[concat.index("-format_whitelist") + 1] == "concat,mov"
    assert concat[concat.index("-safe") + 1] == "0"
    assert concat[concat.index("-c") + 1] == "copy"
    listing = Path(concat[concat.index("-i") + 1]).read_text().splitlines()
    assert len(listing) == 3 * len(result["shards"])
    for offset in range(0, len(listing), 3):
        assert listing[offset].startswith("file '")
        assert listing[offset + 1:offset + 3] == [
            "option format_whitelist mov", "option protocol_whitelist file"]
    for command in (concat, decode, probe):
        assert command[command.index("-protocol_whitelist") + 1] == "file"
        input_at = command.index("-i") if "-i" in command else len(command) - 1
        assert command.index("-protocol_whitelist") < input_at
    for command in (decode, probe):
        assert command[command.index("-f") + 1] == "mov"


@pytest.mark.parametrize("payload", [b"ffconcat version 1.0\n", b"#EXTM3U\n", b"v=0\n"])
async def test_indirect_movie_bytes_refuse_before_project_creation(env, monkeypatch, payload):
    env["source"].write_bytes(payload)
    calls = []

    async def reject(command, timeout):
        calls.append(command)
        assert command[command.index("-protocol_whitelist") + 1] == "file"
        assert "concat" not in command[command.index("-format_whitelist") + 1].split(",")
        raise RuntimeError("Media process exited with status 1: disallowed input format")

    monkeypatch.setattr(project, "run_media_process", reject)
    result = await prepare(env)
    assert "disallowed input format" in result["error"]
    assert len(calls) == 1 and not env["root"].exists()


@pytest.mark.parametrize("payload", [b"ffconcat version 1.0\n", b"#EXTM3U\n"])
async def test_indirect_shard_refusal_cleans_partial_final_and_writes_no_qa(env, monkeypatch, payload):
    result = await frozen(env)
    for shard_id in result["shards"]:
        scope = await execute(env, result, shard_id)
        Path(scope["output_video"]).write_bytes(payload)
        report_path = Path(scope["output_report"])
        report = json.loads(report_path.read_text())
        report["output_video"] = {"sha256": sha(payload), "size_bytes": len(payload)}
        report_path.write_text(json.dumps(report))
    calls = []

    async def reject(command, timeout):
        calls.append(command)
        listing = Path(command[command.index("-i") + 1]).read_text()
        assert "option format_whitelist mov\n" in listing
        assert "option protocol_whitelist file\n" in listing
        assert all(Path(row["path"]).read_bytes() == payload for row in delivery.check_shards("film")[2])
        Path(command[-1]).write_bytes(b"partial output")
        raise RuntimeError("Media process exited with status 1: not a MOV/MP4 shard")

    monkeypatch.setattr(delivery, "run_media_process", reject)
    failed = await commentary_assemble(project_id="film")
    assert "not a MOV/MP4 shard" in failed["error"]
    assert len(calls) == 1
    assert not (env["root"] / "full/commentary.mp4").exists()
    assert not (env["root"] / "full/qa.json").exists()
    assert not (env["root"] / "full/.assembly-claim").exists()
