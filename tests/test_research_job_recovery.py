"""Actual SQLite recovery around mocked research and video submission boundaries."""

import asyncio
from copy import deepcopy
import hashlib
from pathlib import Path
import sqlite3
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import interactions, types

from video_research_mcp.job_store import JobStore
from video_research_mcp.research_jobs import find_operation
from video_research_mcp.tools.research_web import (
    research_web,
    research_web_status,
    research_web_cancel,
)
from video_research_mcp.tools.video import video_batch_analyze
from video_research_mcp.tools.jobs import job_cancel, job_status
import video_research_mcp.video_jobs as batch


@pytest.fixture
def sdk(mock_gemini_client, monkeypatch):
    client = MagicMock()
    client.aio.interactions.create = AsyncMock(
        return_value=interactions.Interaction(id="remote", status="queued")
    )
    client.aio.interactions.get = AsyncMock(
        return_value=interactions.Interaction(
            id="remote",
            status="completed",
            steps=[
                interactions.ModelOutputStep(
                    content=[
                        interactions.TextContent(text="Owned fixture report"),
                    ]
                )
            ],
        )
    )
    client.aio.interactions.cancel = AsyncMock(return_value=None)
    mock_gemini_client["get"].return_value = client
    monkeypatch.setattr("video_research_mcp.weaviate_store.store_deep_research", AsyncMock())
    monkeypatch.setattr("video_research_mcp.weaviate_store.extract_and_store_graph", AsyncMock())
    return client


async def test_restart_poll_retains_exact_request_and_result_without_second_launch(sdk):
    launched = await research_web("Rights-cleared fixture research brief", job_id="stable")
    initial = JobStore().get("stable")
    assert initial["external_id"] == "remote"
    assert initial["request_sha256"] == launched["job_receipt"]["request_sha256"]
    repeated = await research_web("Rights-cleared fixture research brief", job_id="stable")
    assert repeated["interaction_id"] == "remote"
    assert sdk.aio.interactions.create.await_count == 1
    complete = await research_web_status("remote")
    assert complete["topic"] == "Rights-cleared fixture research brief"
    assert complete["report_text"] == "Owned fixture report"
    again = await research_web_status("remote")
    assert again["job_receipt"]["result_sha256"] == complete["job_receipt"]["result_sha256"]
    assert sdk.aio.interactions.get.await_count == 1


async def test_lost_launch_response_is_unknown_and_never_resubmitted(sdk):
    sdk.aio.interactions.create.side_effect = RuntimeError("503 submission outcome unknown")
    first = await research_web("Rights-cleared ambiguous fixture brief", job_id="ambiguous")
    assert first["job_receipt"]["status"] == "unknown"
    repeated = await research_web("Rights-cleared ambiguous fixture brief", job_id="ambiguous")
    assert repeated["status"] == "unknown"
    other = await research_web("New brief cannot authorize duplicate uncertain work")
    assert "already in progress" in other["error"]
    assert sdk.aio.interactions.create.await_count == 1


async def test_cancel_without_ack_and_late_completion_require_reconciliation(sdk):
    await research_web("Rights-cleared cancellation fixture brief")
    requested = await research_web_cancel("remote")
    assert requested["status"] == "cancel_requested"
    assert find_operation("remote")["status"] == "cancel_requested"
    late = await research_web_status("remote")
    assert late["status"] == "completed_after_cancel"
    assert late["reconciliation_required"] is True
    assert late["job_receipt"]["status"] == "partial"


async def test_modified_retained_report_cannot_attest_as_completed(sdk):
    await research_web("Rights-cleared integrity fixture brief", job_id="integrity")
    await research_web_status("remote")
    with sqlite3.connect(JobStore().path) as connection:
        connection.execute(
            "UPDATE jobs SET result_json=? WHERE job_id=?",
            ('{"report_text":"forged"}', "integrity"),
        )
    result = await research_web_status("remote")
    assert "failed readback attestation" in result["error"]
    assert sdk.aio.interactions.get.await_count == 1


@pytest.fixture
def videos(tmp_path, monkeypatch):
    directory = tmp_path / "videos"
    directory.mkdir()
    for name in ("a", "b", "c", "d"):
        (directory / f"{name}.mp4").write_bytes(name.encode())

    async def prepare(path, instruction):
        data = Path(path).read_bytes()
        return (
            types.Content(parts=[types.Part.from_bytes(data=data, mime_type="video/mp4")]),
            hashlib.sha256(data).hexdigest(),
            "",
        )

    monkeypatch.setattr(batch, "_video_file_content", prepare)
    return directory


async def test_mixed_batch_retains_denominator_bounds_and_repeat_results(videos, monkeypatch):
    active = maximum = calls = 0

    async def analyze(*args, source_label, **kwargs):
        nonlocal active, maximum, calls
        calls += 1
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        if Path(source_label).stem == "c":
            return {"error": "fixture provider refusal"}
        if Path(source_label).stem == "d":
            raise ValueError("fixture source failure")
        return {"summary": "fixture success"}

    monkeypatch.setattr(batch, "analyze_video", analyze)
    result = await video_batch_analyze(str(videos), max_concurrency=2, job_id="mixed")
    assert (result["total_files"], result["successful"], result["failed"], result["partial"]) == (
        4,
        2,
        2,
        0,
    )
    assert result["job_receipt"]["status"] == "partial"
    assert maximum == 2
    assert calls == 4
    repeated = await video_batch_analyze(str(videos), max_concurrency=2, job_id="mixed")
    assert repeated["items"] == result["items"]
    assert calls == 4


async def test_stale_batch_never_resends_running_item(videos, monkeypatch):
    analysis = AsyncMock(return_value={"summary": "fixture"})
    monkeypatch.setattr(batch, "analyze_video", analysis)
    seed = await video_batch_analyze(str(videos), max_files=2, job_id="request-seed")
    request = JobStore().get("request-seed")["request"]
    store = JobStore()
    revision = hashlib.sha256(Path(batch.__file__).read_bytes()).hexdigest()
    store.create("video_batch", request, revision, job_id="restart")
    store.claim("restart", "lost-owner", now=0, lease_seconds=1)
    items = deepcopy(request["items"])
    items[0]["status"] = "running"
    store.checkpoint("restart", "lost-owner", result=batch.batch_result(str(videos), items), now=0)
    analysis.reset_mock()
    result = await video_batch_analyze(str(videos), max_files=2, job_id="restart")
    assert seed["successful"] == 2
    assert result["partial"] == 1
    assert result["successful"] == 1
    assert result["items"][0]["status"] == "unknown"
    assert analysis.await_count == 1


async def test_batch_cancellation_stops_queue_and_retains_late_result(videos, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def analyze(*args, **kwargs):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {"summary": "late fixture completion"}

    monkeypatch.setattr(batch, "analyze_video", analyze)
    task = asyncio.create_task(
        video_batch_analyze(str(videos), max_concurrency=1, job_id="cancel-batch")
    )
    await asyncio.wait_for(started.wait(), timeout=5)
    requested = await job_cancel("cancel-batch")
    assert requested["status"] == "cancel_requested"
    assert requested["provider_termination"] == "unknown"
    release.set()
    result = await task
    assert (result["total_files"], result["partial"], result["canceled"]) == (4, 1, 3)
    assert result["job_receipt"]["status"] == "partial"
    assert result["items"][0]["reconciliation_required"] is True
    assert calls == 1
    assert (await job_status("cancel-batch"))["result_sha256"] == result["job_receipt"][
        "result_sha256"
    ]


async def test_wrong_provider_identity_cannot_reconcile_local_operation(sdk):
    await research_web("Owned identity fixture", job_id="identity")
    sdk.aio.interactions.get.return_value.id = "different-operation"
    result = await research_web_status("remote")
    assert "different interaction ID" in result["error"]
    assert JobStore().get("identity")["status"] == "running"
    sdk.aio.interactions.cancel.return_value = interactions.Interaction(
        id="different-operation", status="cancelled"
    )
    result = await research_web_cancel("remote")
    assert "different cancellation interaction ID" in result["error"]
    assert JobStore().get("identity")["status"] == "cancel_requested"


async def test_lost_batch_ownership_before_dispatch_never_transmits(videos, monkeypatch):
    analysis = AsyncMock(return_value={"summary": "must not be submitted"})
    monkeypatch.setattr(batch, "analyze_video", analysis)
    checkpoint = JobStore.checkpoint

    def lose_ownership(self, job_id, owner, **kwargs):
        if job_id == "lost-owner":
            return False
        return checkpoint(self, job_id, owner, **kwargs)

    monkeypatch.setattr(JobStore, "checkpoint", lose_ownership)
    result = await video_batch_analyze(str(videos), job_id="lost-owner")
    assert "error" in result
    assert analysis.await_count == 0


async def test_batch_cancel_during_preparation_stops_provider_dispatch(videos, monkeypatch):
    async def prepare(*args):
        JobStore().cancel("prepare-cancel")
        data = Path(args[0]).read_bytes()
        return types.Content(parts=[]), hashlib.sha256(data).hexdigest(), ""

    analysis = AsyncMock()
    monkeypatch.setattr(batch, "_video_file_content", prepare)
    monkeypatch.setattr(batch, "analyze_video", analysis)
    result = await video_batch_analyze(str(videos), max_concurrency=1, job_id="prepare-cancel")
    assert result["canceled"] == 4
    assert result["job_receipt"]["status"] == "cancelled"
    assert analysis.await_count == 0


async def test_completed_create_retains_report_without_polling_again(sdk):
    sdk.aio.interactions.create.return_value = sdk.aio.interactions.get.return_value
    result = await research_web("Owned immediate fixture", job_id="immediate")
    assert result["report_text"] == "Owned fixture report"
    retained = await research_web_status("remote")
    assert retained["report_text"] == result["report_text"]
    assert sdk.aio.interactions.get.await_count == 0


@pytest.mark.parametrize("operation", [research_web_status, research_web_cancel])
@pytest.mark.parametrize(
    "field,value", [("external_id", "unrelated"), ("result_json", '{"status":"forged"}')]
)
async def test_corrupted_active_operation_cannot_call_provider(sdk, operation, field, value):
    await research_web("Owned binding fixture", job_id="binding")
    with sqlite3.connect(JobStore().path) as connection:
        connection.execute(f"UPDATE jobs SET {field}=? WHERE job_id=?", (value, "binding"))
    result = await operation("unrelated" if field == "external_id" else "remote")
    assert "failed readback attestation" in result["error"]
    assert sdk.aio.interactions.get.await_count == 0
    assert sdk.aio.interactions.cancel.await_count == 0
    assert JobStore().get("binding")["attestation"]["result_integrity"] == "mismatch"
    assert JobStore().get("binding")["status"] == "running"


async def test_source_mutation_during_preparation_never_dispatches(videos, monkeypatch):
    async def changed_prepare(path, instruction):
        Path(path).write_bytes(b"changed fixture bytes")
        return types.Content(parts=[]), hashlib.sha256(Path(path).read_bytes()).hexdigest(), ""

    analysis = AsyncMock()
    monkeypatch.setattr(batch, "_video_file_content", changed_prepare)
    monkeypatch.setattr(batch, "analyze_video", analysis)
    result = await video_batch_analyze(str(videos), job_id="preparation-change")
    assert result["failed"] == 4
    assert result["successful"] == 0
    assert analysis.await_count == 0
    assert all("frozen batch source" in item["error"] for item in result["items"])


async def test_job_status_artifact_readback_keeps_event_loop_responsive(tmp_path, monkeypatch):
    import video_research_mcp.job_store as store_module

    output = tmp_path / "owned-output.mp4"
    output.write_bytes(b"owned fixture")
    store = JobStore()
    store.create("render", {"project_id": "owned"}, "fixture", job_id="slow-artifact")
    store.claim("slow-artifact", "owner")
    store.checkpoint(
        "slow-artifact",
        "owner",
        status="completed",
        result={"output": "fixture"},
        artifact_hashes={str(output): hashlib.sha256(output.read_bytes()).hexdigest()},
        release=True,
    )
    original = store_module._artifact_readback
    started, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    def controlled_readback(values, check=None, max_bytes=None):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=5)
        return original(values, check, max_bytes)

    monkeypatch.setattr(store_module, "_artifact_readback", controlled_readback)
    task = asyncio.create_task(job_status("slow-artifact"))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        await asyncio.wait_for(asyncio.sleep(0), timeout=1)
        assert not task.done()
    finally:
        release.set()
    result = await asyncio.wait_for(task, timeout=5)
    assert result["attestation"]["verified"]


async def test_inline_payload_mutation_never_dispatches(videos, monkeypatch):
    async def changed_payload(path, instruction):
        original = Path(path).read_bytes()
        content = types.Content(
            parts=[types.Part.from_bytes(data=b"different inline bytes", mime_type="video/mp4")]
        )
        return content, hashlib.sha256(original).hexdigest(), ""

    analysis = AsyncMock()
    monkeypatch.setattr(batch, "_video_file_content", changed_payload)
    monkeypatch.setattr(batch, "analyze_video", analysis)
    result = await video_batch_analyze(str(videos), job_id="payload-change")
    assert result["failed"] == 4
    assert analysis.await_count == 0
    assert all("bytes differ" in item["error"] for item in result["items"])
