"""Controlled regressions for DSP deadline ownership, actual audio windows and manifests."""

import asyncio
import hashlib
import os
import threading
import time
from types import SimpleNamespace

import pytest

from video_research_mcp import audio_dsp, config, job_store
from video_research_mcp.image_manifest import read_manifest, write_manifest
from video_research_mcp.job_store import JobStore
from video_research_mcp.models.audio_dsp import AudioDspRequest


def record(path):
    body = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}


def controller(tmp_path, monkeypatch, timeout=2):
    """Keep actual admission and DB ownership while excluding numerical/native evaluation."""
    monkeypatch.setattr(
        config, "_config", config.ServerConfig(gemini_api_key="fixture", cache_dir=str(tmp_path))
    )
    monkeypatch.setattr(
        audio_dsp, "get_config", lambda: SimpleNamespace(media_acquire_timeout_seconds=timeout)
    )
    source = tmp_path / "source.wav"
    source.write_bytes(b"fixed regression source")
    artifact, manifest = tmp_path / "selected.wav", tmp_path / "manifest.json"
    artifact.write_bytes(b"\0" * (4 * 1024 * 1024))
    manifest.write_bytes(b'{"regression":true}')
    calls = []

    async def runtime(*args):
        return {"version": "controlled"}

    async def evaluate(*args):
        calls.append(1)
        return {"status": "complete", "artifacts": [record(artifact)], "manifest": record(manifest)}

    monkeypatch.setattr(audio_dsp, "runtime_binding", runtime)
    monkeypatch.setattr(audio_dsp, "evaluate", evaluate)
    request = AudioDspRequest(
        file_path=str(source), expected_source_sha256=record(source)["sha256"], job_id="controlled"
    )
    return request, artifact, calls


class SlowReader:
    """Delay actual reads of one owned artifact; keep full hashing and cooperative guards."""

    def __init__(self, stream, started, active):
        self.stream, self.started, self.active = stream, started, active
        self.worker = threading.get_ident()

    def __enter__(self):
        self.stream.__enter__()
        self.active.add(self.worker)
        return self

    def __exit__(self, *args):
        try:
            return self.stream.__exit__(*args)
        finally:
            self.active.remove(self.worker)

    def fileno(self):
        return self.stream.fileno()

    def read(self, size):
        self.started.set()
        time.sleep(0.06)
        return self.stream.read(size)


def slow_artifact(monkeypatch, artifact, enabled=lambda: True):
    """Patch slowness at real file reads without replacing artifact attestation."""
    original = os.fdopen
    identity = artifact.stat().st_dev, artifact.stat().st_ino
    started, active = threading.Event(), set()

    def fdopen(descriptor, *args, **kwargs):
        stream = original(descriptor, *args, **kwargs)
        current = os.fstat(stream.fileno())
        if (current.st_dev, current.st_ino) == identity and enabled():
            return SlowReader(stream, started, active)
        return stream

    monkeypatch.setattr(job_store.os, "fdopen", fdopen)
    return started, active


async def entered(event):
    """Fail promptly if the intended controlled read never starts."""
    async with asyncio.timeout(1):
        while not event.is_set():
            await asyncio.sleep(0.002)


async def heartbeat(done, ticks):
    while not done.is_set():
        ticks.append(time.monotonic())
        await asyncio.sleep(0.002)


async def repeated_cancel(task):
    for _ in range(3):
        task.cancel()
        await asyncio.sleep(0.004)
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_deadline_stream_readback_keeps_loop_live_and_never_commits_complete(
    tmp_path, monkeypatch
):
    """GIVEN a slow real artifact WHEN the deadline expires THEN work joins before failure."""
    request, artifact, _ = controller(tmp_path, monkeypatch, timeout=0.08)
    started, active = slow_artifact(monkeypatch, artifact)
    done, ticks = asyncio.Event(), []
    pulse = asyncio.create_task(heartbeat(done, ticks))
    began = time.monotonic()
    try:
        result = await audio_dsp.execute(request)
    finally:
        done.set()
        await pulse
    assert started.is_set() and len(ticks) >= 3 and time.monotonic() - began < 0.6
    assert not active and result["metadata"]["status"] == "failed"
    assert result["metadata"]["category"] == "ARTIFACT_GENERATION_FAILED"
    assert "0.08-second deadline" in result["metadata"]["error"]
    assert result["metadata"]["retryable"] is False
    assert result["metadata"]["retry_after_seconds"] is None
    durable = JobStore().get(request.job_id)
    assert durable["status"] == "failed" and durable["owner"] is None
    assert durable["result"]["status"] != "complete"


@pytest.mark.parametrize("phase", ["precommit", "replay", "postcommit"])
async def test_repeated_cancel_joins_readback_and_preserves_terminal_boundary(
    tmp_path, monkeypatch, phase
):
    """GIVEN real DB/artifacts WHEN delivery is cancelled THEN committed work stays immutable."""
    request, artifact, calls = controller(tmp_path, monkeypatch)
    if phase == "replay":
        assert (await audio_dsp.execute(request))["metadata"]["status"] == "complete"
    committed = threading.Event()
    original = JobStore.checkpoint

    def checkpoint(self, *args, **kwargs):
        changed = original(self, *args, **kwargs)
        if changed and kwargs["status"] == "completed":
            committed.set()
        return changed

    monkeypatch.setattr(JobStore, "checkpoint", checkpoint)
    enabled = committed.is_set if phase == "postcommit" else lambda: True
    started, active = slow_artifact(monkeypatch, artifact, enabled)
    task = asyncio.create_task(audio_dsp.execute(request))
    await entered(started)
    await repeated_cancel(task)
    assert not active and len(calls) == 1
    durable = JobStore(tmp_path / "jobs.sqlite3").get(request.job_id)
    expected = "cancelled" if phase == "precommit" else "completed"
    assert durable["status"] == expected and durable["owner"] is None
    assert durable["attempts"] == 1 and durable["attestation"]["verified"]


async def test_cancel_after_claim_and_again_during_cleanup_releases_real_owner(
    tmp_path, monkeypatch
):
    """GIVEN a committed claim WHEN cancellation repeats during cleanup THEN both threads join."""
    request, _, calls = controller(tmp_path, monkeypatch)
    claim_started, cleanup_started = threading.Event(), threading.Event()
    active = set()
    original_claim, original_checkpoint = JobStore.claim, JobStore.checkpoint

    def claim(self, *args, **kwargs):
        value = original_claim(self, *args, **kwargs)
        worker = threading.get_ident()
        active.add(worker)
        claim_started.set()
        try:
            while True:
                self.readback_check()
                time.sleep(0.002)
        finally:
            active.remove(worker)
        return value

    def checkpoint(self, *args, **kwargs):
        if kwargs["status"] == "cancelled":
            cleanup_started.set()
            until = time.monotonic() + 0.06
            while time.monotonic() < until:
                self.readback_check()
                time.sleep(0.002)
        return original_checkpoint(self, *args, **kwargs)

    monkeypatch.setattr(JobStore, "claim", claim)
    monkeypatch.setattr(JobStore, "checkpoint", checkpoint)
    task = asyncio.create_task(audio_dsp.execute(request))
    await entered(claim_started)
    task.cancel()
    await entered(cleanup_started)
    await repeated_cancel(task)
    assert not active and not calls
    durable = JobStore().get(request.job_id)
    assert durable["status"] == "cancelled" and durable["owner"] is None
    assert durable["attempts"] == 1 and durable["lease_until"] is None


def test_guard_failure_rolls_back_terminal_checkpoint(tmp_path):
    """GIVEN a live owner WHEN the precommit guard fails THEN SQL terminal changes roll back."""
    store = JobStore(tmp_path / "checkpoint.sqlite3")
    job = store.create("audio_dsp", {}, "fixed")
    store.claim(job["job_id"], "owner")

    def expired():
        raise TimeoutError("controlled expiry immediately before commit")

    store.readback_check = expired
    with pytest.raises(TimeoutError, match="immediately before commit"):
        store.checkpoint(job["job_id"], "owner", status="completed", result={}, release=True)
    durable = JobStore(store.path).get(job["job_id"])
    assert durable["status"] == "running" and durable["owner"] == "owner"
    assert durable["result"] is None


@pytest.mark.parametrize("compare", [False, True])
async def test_delayed_audio_counts_decoded_duration_instead_of_initial_gap(
    tmp_path, monkeypatch, compare
):
    """GIVEN delayed audio WHEN omitted ends resolve THEN only selected audio uses the budget."""
    monkeypatch.setattr(
        config, "_config", config.ServerConfig(gemini_api_key="fixture", cache_dir=str(tmp_path))
    )
    primary, reference = tmp_path / "primary.wav", tmp_path / "reference.wav"
    primary.write_bytes(b"primary source")
    reference.write_bytes(b"reference source")
    durations = []

    async def source(owned):
        first, end = (30, 31) if owned.original == primary else (45, 60)
        return {"first_audio_seconds": first, "audio_end_seconds": end}

    async def analyze(owned, window, source, request):
        end, _ = audio_dsp.audio_window(source, window.start_seconds, window.end_seconds, 30)
        duration = end - max(window.start_seconds, source["first_audio_seconds"])
        durations.append(duration)
        return {"selected_seconds": duration, "selection": {}}, b"", []

    async def runtime(*args):
        return {"version": "controlled"}

    async def publish(payload, *args):
        return payload

    monkeypatch.setattr(audio_dsp, "audio_source", source)
    monkeypatch.setattr(audio_dsp, "analyze_one", analyze)
    monkeypatch.setattr(audio_dsp, "runtime_binding", runtime)
    monkeypatch.setattr(audio_dsp, "report", lambda request, rows, *args: {"analyses": rows})
    monkeypatch.setattr(audio_dsp, "publish", publish)
    values = {"file_path": str(primary), "expected_source_sha256": record(primary)["sha256"]}
    if compare:
        values.update(operation="compare", reference={
            "file_path": str(reference), "expected_source_sha256": record(reference)["sha256"]
        })
    result = await audio_dsp.evaluate(
        AudioDspRequest(**values), None, {"runtime": {"version": "controlled"}}, time.monotonic() + 2, {}
    )
    assert durations == ([1, 15] if compare else [1])
    assert sum(row["selected_seconds"] for row in result["analyses"]) <= 30


@pytest.mark.parametrize("mutation", ["tamper", "remove"])
async def test_reference_manifest_uses_input_limit_and_checks_all_source_bytes(
    tmp_path, monkeypatch, mutation
):
    """GIVEN a reference above the output cap WHEN it changes THEN generic read/write reject it."""
    monkeypatch.setattr(config, "_config", config.ServerConfig(
        gemini_api_key="fixture", media_max_input_bytes=12 * 1024 * 1024
    ))
    primary, reference, output = (tmp_path / name for name in ("primary", "reference", "output"))
    primary.write_bytes(b"primary")
    reference.write_bytes(b"r" * (9 * 1024 * 1024))
    output.write_bytes(b"tiny")
    sources, artifact = [record(primary), record(reference)], record(output)
    payload = {"source": sources[0], "sources": sources, "artifacts": [artifact], "artifact": artifact}
    manifest = await write_manifest(payload, tmp_path)
    verified = await read_manifest(manifest["path"], manifest["sha256"])
    assert verified["verified"] and verified["sources"] == sources
    if mutation == "tamper":
        with reference.open("r+b") as writer:
            writer.write(b"changed")
    else:
        reference.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        await read_manifest(manifest["path"], manifest["sha256"])
    rejected = tmp_path / "rejected"
    rejected.mkdir()
    with pytest.raises((ValueError, FileNotFoundError)):
        await write_manifest(payload, rejected)
    assert not (rejected / "manifest.json").exists()


async def test_single_source_manifest_remains_exactly_readable(tmp_path):
    """GIVEN the existing singleton contract WHEN re-read THEN its source and output verify."""
    source, output = tmp_path / "source", tmp_path / "output"
    source.write_bytes(b"single source")
    output.write_bytes(b"single output")
    payload = {"source": record(source), "artifacts": [record(output)]}
    manifest = await write_manifest(payload, tmp_path)
    verified = await read_manifest(manifest["path"], manifest["sha256"])
    assert verified["verified"] and verified["source"] == payload["source"]
    assert "sources" not in verified
