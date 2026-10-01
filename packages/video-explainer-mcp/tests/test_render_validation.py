"""Exact render snapshot and codec-proof controls at the native subprocess boundary."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from video_explainer_mcp.job_store import JobStore
from video_explainer_mcp.render_artifacts import file_revision, verify_output
from video_explainer_mcp.render_validation import MAX_VIDEO_BYTES, qualify_render, qualification_valid
from video_explainer_mcp.tools.render_jobs import explainer_render_poll


class NativeReply:
    """Use actual bounded pipe readers while replacing only process creation."""

    def __init__(self, stdout=b"", stderr=b"", code=0):
        self.pid = 1_000_000_000
        self.returncode = code
        self.stdout, self.stderr = asyncio.StreamReader(), asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stderr.feed_data(stderr)
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.waits = 0

    async def wait(self):
        self.waits += 1
        return self.returncode


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name in ("ffprobe", "ffmpeg"):
        target = binaries / name
        target.write_bytes(f"Owned nonexecuted {name} binary marker".encode())
        target.chmod(0o700)
    monkeypatch.setenv("PATH", str(binaries))
    output = tmp_path / "owned.mp4"
    output.write_bytes(b"Synthetic codec-edge fixture, not real playable MP4")
    return {"path": str(output), **file_revision(output)}, binaries


def _metadata() -> dict:
    return {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1280,
                         "height": 720, "pix_fmt": "yuv420p"}],
            "format": {"duration": "2.0"}}


def _native(monkeypatch, probe=None, *, failure=None, mutate=None):
    """Keep production snapshot/JSON/pipe/identity checks active with one native-edge stub."""
    calls, replies, snapshots = [], [], []
    body = json.dumps(_metadata()).encode() if probe is None else probe

    async def spawn(*command, **kwargs):
        name = Path(command[0]).name
        calls.append((command, kwargs))
        path = Path(command[-1]) if name == "ffprobe" else Path(command[command.index("-i") + 1])
        snapshots.append((str(path), path.read_bytes()))
        if mutate:
            mutate(name)
        error = b"owned native failure" if failure == name else b""
        stdout = body if name == "ffprobe" else b""
        if failure == "decode_stdout" and name == "ffmpeg":
            stdout = b"unexpected decode output"
        if failure == "probe_stderr" and name == "ffprobe":
            error = b"malformed media warning"
        reply = NativeReply(stdout, error, int(failure == name))
        replies.append(reply)
        return reply

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return calls, replies, snapshots


async def test_private_exact_snapshot_is_probed_then_every_stream_is_decoded(candidate, monkeypatch):
    artifact, _ = candidate
    expected = Path(artifact["path"]).read_bytes()
    calls, replies, snapshots = _native(monkeypatch)
    proof = await qualify_render(artifact, "720p")
    assert proof["artifact_sha256"] == artifact["sha256"]
    assert proof["full_decode"] is True and proof["coverage"] == "all video frames and audio packets"
    assert proof["media"] == {"codec": "h264", "width": 1280, "height": 720,
                              "duration_seconds": 2.0, "pixel_format": "yuv420p"}
    assert [Path(command[0]).name for command, _ in calls] == ["ffprobe", "ffmpeg"]
    assert all(body == expected and path != artifact["path"] for path, body in snapshots)
    assert snapshots[0][0] == snapshots[1][0] and not Path(snapshots[0][0]).exists()
    probe, decode = calls[0][0], calls[1][0]
    assert probe[probe.index("-protocol_whitelist") + 1] == "file,pipe"
    assert decode[decode.index("-map") + 1] == "0:v:0" and "0:a?" in decode
    assert "-xerror" in decode and "-nostdin" in decode and decode[-2:] == ("null", "-")
    assert all(kwargs["stdin"] == asyncio.subprocess.DEVNULL for _, kwargs in calls)
    assert all(reply.waits == 1 for reply in replies)
    assert proof["real_renderer_verified"] is False and proof["visual_audio_semantics"] == "not_verified"


@pytest.mark.parametrize("damage", ["malformed", "oversized", "no_stream", "two_streams", "codec", "dimensions", "nan", "infinite", "zero", "too_long"])
async def test_unreadable_or_unqualified_metadata_stops_before_decode(candidate, monkeypatch, damage):
    artifact, _ = candidate
    value = _metadata()
    if damage == "malformed":
        body = b"{malformed JSON"
    elif damage == "oversized":
        body = b" " * (16384 + 1)
    else:
        if damage == "no_stream":
            value["streams"] = []
        elif damage == "two_streams":
            value["streams"].append(deepcopy(value["streams"][0]))
        elif damage == "codec":
            value["streams"][0]["codec_name"] = "vp9"
        elif damage == "dimensions":
            value["streams"][0]["height"] = 721
        else:
            value["format"]["duration"] = {"nan": "NaN", "infinite": "Infinity", "zero": "0", "too_long": "14401"}[damage]
        body = json.dumps(value).encode()
    calls, _, _ = _native(monkeypatch, body)
    with pytest.raises(ValueError):
        await qualify_render(artifact, "720p")
    assert len(calls) == 1 and Path(calls[0][0][0]).name == "ffprobe"


@pytest.mark.parametrize("failure", ["ffprobe", "ffmpeg", "probe_stderr", "decode_stdout"])
async def test_probe_or_full_decode_failure_has_no_accepted_proof(candidate, monkeypatch, failure):
    artifact, _ = candidate
    calls, replies, _ = _native(monkeypatch, failure=failure)
    with pytest.raises((RuntimeError, ValueError)):
        await qualify_render(artifact, "720p")
    assert len(calls) == (1 if failure in {"ffprobe", "probe_stderr"} else 2)
    assert all(reply.waits >= 1 for reply in replies)
    if failure in {"ffprobe", "ffmpeg"}:
        assert next(reply for reply in replies if reply.returncode).waits >= 2


async def test_shared_native_stream_ceiling_is_enforced_before_decode(candidate, monkeypatch):
    artifact, _ = candidate
    calls, replies, _ = _native(monkeypatch, b"x" * (1024 * 1024 + 1))
    with pytest.raises(RuntimeError, match="1 MiB"):
        await qualify_render(artifact, "720p")
    assert len(calls) == 1 and replies[0].waits >= 2


@pytest.mark.parametrize("damage", ["digest", "size", "changed_bytes"])
async def test_snapshot_commitment_mismatch_prevents_any_native_call(candidate, monkeypatch, damage):
    artifact, _ = candidate
    if damage == "digest":
        artifact["sha256"] = "0" * 64
    elif damage == "size":
        artifact["size_bytes"] += 1
    else:
        Path(artifact["path"]).write_bytes(b"Changed after admission")
    calls, _, _ = _native(monkeypatch)
    with pytest.raises(ValueError, match="changed before codec qualification"):
        await qualify_render(artifact, "720p")
    assert calls == []


@pytest.mark.parametrize("kind", ["empty", "oversize", "directory", "symlink", "fifo"])
async def test_nonregular_empty_or_oversize_snapshot_is_rejected(candidate, monkeypatch, kind, tmp_path):
    artifact, _ = candidate
    path = Path(artifact["path"])
    if kind == "empty":
        path.write_bytes(b"")
    elif kind == "oversize":
        with path.open("wb") as stream:
            stream.truncate(MAX_VIDEO_BYTES + 1)
    else:
        path.unlink()
        if kind == "directory":
            path.mkdir()
        elif kind == "symlink":
            target = tmp_path / "outside.mp4"
            target.write_bytes(b"Outside candidate")
            path.symlink_to(target)
        else:
            if not hasattr(os, "mkfifo"):
                pytest.skip("FIFO source guard requires POSIX")
            os.mkfifo(path)
    calls, _, _ = _native(monkeypatch)
    with pytest.raises((OSError, ValueError)):
        await qualify_render(artifact, "720p")
    assert calls == []


@pytest.mark.parametrize("binary", ["ffprobe", "ffmpeg"])
async def test_native_executable_revision_change_invalidates_qualification(candidate, monkeypatch, binary):
    artifact, binaries = candidate

    def mutate(name):
        if name == "ffmpeg":
            (binaries / binary).write_bytes(b"Changed executable after identity admission")

    calls, _, _ = _native(monkeypatch, mutate=mutate)
    with pytest.raises(ValueError, match="codec executable changed"):
        await qualify_render(artifact, "720p")
    assert len(calls) == 2


@pytest.mark.parametrize("field,value", [("policy", "other-policy"), ("full_decode", False), ("artifact_sha256", "0" * 64), ("size_bytes", 0)])
async def test_persisted_proof_is_bound_to_policy_and_exact_artifact_commitment(candidate, monkeypatch, field, value):
    artifact, _ = candidate
    _native(monkeypatch)
    proof = await qualify_render(artifact, "720p")
    assert qualification_valid({**artifact, "qualification": proof}) is True
    changed = deepcopy(proof)
    changed[field] = value
    assert qualification_valid({**artifact, "qualification": changed}) is False
    assert qualification_valid(artifact) is False


async def test_exact_proof_reuses_after_sqlite_restart_without_native_repeat_then_tamper_is_unknown(candidate, monkeypatch):
    """Real durable receipt readback, with the codec edge explicitly simulated."""
    artifact, _ = candidate
    calls, _, _ = _native(monkeypatch)
    proof = await qualify_render(artifact, "720p")
    proof["test_fixture"] = "Synthetic subprocess responses; no actual codec/renderer run"
    output = {**artifact, "qualification": proof}
    store = JobStore()
    row = store.create("render", {"project_id": "fixture", "resolution": "720p", "fast": True,
                                  "render_timeout": 10}, "owned-source-fixture")
    assert store.claim(row["job_id"], "owned-worker")
    assert store.checkpoint(row["job_id"], "owned-worker", status="completed",
                            result={"output": output}, artifact_hashes={artifact["path"]: artifact["sha256"]})
    persisted = JobStore().get(row["job_id"])
    assert persisted["attestation"]["verified"] is True
    current = await explainer_render_poll(row["job_id"])
    assert current["status"] == "completed" and current["playability_verified"] is True
    assert current["qualification"]["artifact_sha256"] == artifact["sha256"]
    assert len(calls) == 2 and verify_output(artifact) is True
    Path(artifact["path"]).write_bytes(b"Tampered after completed proof")
    changed = await explainer_render_poll(row["job_id"])
    assert changed["status"] == "unknown" and changed["recorded_status"] == "completed"
    assert changed["artifact_verified"] is changed["playability_verified"] is False
    assert changed["output_file"] == "" and changed["qualification"] is None
    assert len(calls) == 2
