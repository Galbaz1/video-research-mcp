"""Actual budget/core calls with only SDK transport mocked and isolated durable state."""

import asyncio
import json
import os
import subprocess
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import types

from video_research_mcp.job_store import JobStore
from video_research_mcp.models.video_windows import WindowAnalysisRequest, WindowRunLimits
from video_research_mcp.video_window_plan import plan_windows
from video_research_mcp.video_window_run import execute_windows


def bounds(**changes):
    return WindowRunLimits(
        **{
            "max_calls": 6,
            "max_tokens": 100000,
            "max_output_tokens": 1000,
            "max_frames": 20,
            "max_windows": 6,
            **changes,
        }
    )


def response(reason="STOP", usage=True, text='{"answer":"bounded window"}'):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(parts=[types.Part(text=text)]), finish_reason=reason
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=3,
            candidates_token_count=4,
            thoughts_token_count=0,
            total_token_count=7,
        )
        if usage
        else None,
    )


@pytest.fixture
def scenario(tmp_path, monkeypatch, clean_config, mock_weaviate_disabled):
    monkeypatch.setenv("VRM_JOB_DB", str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "owned.mp4"
    source.write_bytes(b"original rights-owned unit fixture; no media quality claim")
    request = WindowAnalysisRequest(
        file_path=str(source),
        instruction="Inspect only requested windows",
        end_ms=1200,
        window_ms=400,
        fps=2.0,
        output_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
    )
    client = MagicMock()
    client.aio.models.count_tokens = AsyncMock(
        return_value=types.CountTokensResponse(total_tokens=3)
    )
    client.aio.models.generate_content = AsyncMock(return_value=response())
    with patch("video_research_mcp.client.GeminiClient.get", return_value=client):
        yield source, request, client


async def test_actual_inline_count_generation_static_windows_and_single_preparation(scenario):
    """GIVEN three windows WHEN executed THEN actual core/budget send each metadata pair once."""
    source, request, client = scenario
    plan = plan_windows(request, bounds())
    from video_research_mcp.tools.video_file import _video_file_content

    with patch(
        "video_research_mcp.video_window_run._video_file_content", wraps=_video_file_content
    ) as prepare:
        result = await execute_windows(plan, bounds(), job_id="inline")
    assert prepare.await_count == 1
    assert result["status"] == "completed" and result["covered_windows"] == [0, 1, 2]
    assert result["remaining_windows"] == result["unknown_windows"] == []
    assert result["run_usage"]["provider_calls"] == result["execution_usage"]["provider_calls"] == 6
    assert (
        result["run_usage"]["requested_windows"] == 6
        and result["run_usage"]["requested_frames"] == 6
    )
    assert result["run_usage"]["output_tokens"] == 12
    assert (
        client.aio.models.count_tokens.await_count
        == client.aio.models.generate_content.await_count
        == 3
    )
    for index, (count, generation) in enumerate(
        zip(
            client.aio.models.count_tokens.call_args_list,
            client.aio.models.generate_content.call_args_list,
        )
    ):
        for call in (count, generation):
            content = call.kwargs["contents"]
            part = content.parts[0]
            assert part.inline_data.data == source.read_bytes()
            assert part.media_processing == types.MediaProcessing.STATIC
            assert part.video_metadata.model_dump(exclude_none=True) == {
                "fps": 2.0,
                "start_offset": f"{index * 400 // 1000}.{index * 400 % 1000:03d}s",
                "end_offset": f"{(index + 1) * 400 // 1000}.{(index + 1) * 400 % 1000:03d}s",
            }
        assert "original source timeline" in generation.kwargs["contents"].parts[1].text
    assert (
        result["observed_coverage"] == "unknown"
        and result["job_receipt"]["attestation"]["verified"]
    )


async def test_file_uri_part_is_static_with_opaque_upload_freshness(scenario):
    source, request, client = scenario
    plan = plan_windows(request, bounds())
    uri = "https://files.example.invalid/owned"

    async def prepared(file_path, prompt, *, video_metadata):
        media = types.Part.from_uri(file_uri=uri, mime_type="video/mp4")
        media.video_metadata = video_metadata
        return types.Content(parts=[media, types.Part(text=prompt)]), plan["source"]["sha256"], uri

    with patch(
        "video_research_mcp.video_window_run._video_file_content", side_effect=prepared
    ) as prepare:
        result = await execute_windows(plan, bounds(), job_id="uri")
    assert prepare.await_count == 1 and result["status"] == "completed"
    assert result["preparation"]["uploaded_uri_freshness"] == "unknown"
    for call in client.aio.models.generate_content.call_args_list:
        part = call.kwargs["contents"].parts[0]
        assert (
            part.file_data.file_uri == uri and part.media_processing == types.MediaProcessing.STATIC
        )
        assert part.video_metadata.fps == 2.0
    assert all(item["result"]["source_sha256"] is None for item in result["windows"])


async def test_two_call_partial_restart_and_idempotent_child(scenario):
    """GIVEN two calls WHEN continued THEN covered results survive and repeated token never sends."""
    source, request, client = scenario
    first_limits = bounds(max_calls=2, max_windows=2)
    plan = plan_windows(request, first_limits)
    parent = await execute_windows(plan, first_limits, job_id="parent")
    assert parent["status"] == "partial" and parent["continuation_token"] == "parent"
    assert parent["covered_windows"] == [0] and parent["remaining_windows"] == [1, 2]
    assert parent["run_usage"]["provider_calls"] == 2
    restarted = JobStore(os.environ["VRM_JOB_DB"]).get("parent")
    assert restarted["result"]["windows"][0] == parent["windows"][0]
    script = "import json,sys;from video_research_mcp.job_store import JobStore;j=JobStore(sys.argv[1]).get('parent');print(json.dumps({'request':j['request']['plan'],'result':j['result'],'attestation':j['attestation']}))"
    proc = subprocess.run(
        [sys.executable, "-c", script, os.environ["VRM_JOB_DB"]],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    readback = json.loads(proc.stdout)
    assert readback["request"] == plan and readback["result"]["covered_windows"] == [0]
    assert readback["attestation"]["verified"]
    child_limits = bounds(max_calls=4, max_windows=4)
    child = await execute_windows(plan, child_limits, continuation_token="parent")
    repeated = await execute_windows(plan, child_limits, continuation_token="parent")
    assert child["status"] == repeated["status"] == "completed"
    assert child["job_receipt"]["job_id"] == repeated["job_receipt"]["job_id"]
    assert (
        child["run_usage"]["provider_calls"] == 4
        and child["execution_usage"]["provider_calls"] == 6
    )
    assert child["windows"][0] == parent["windows"][0]
    assert client.aio.models.generate_content.await_count == 3
    with pytest.raises(ValueError, match="binding differs"):
        await execute_windows(plan, bounds(), continuation_token="parent")
    assert client.aio.models.generate_content.await_count == 3


async def test_new_limits_preserve_parent_automatic_fps(scenario):
    _, request, client = scenario
    request = request.model_copy(update={"fps": None, "window_ms": 400000, "end_ms": 1200000})
    initial = bounds(max_calls=2, max_windows=2, max_frames=6)
    parent_plan = plan_windows(request, initial)
    parent = await execute_windows(parent_plan, initial, job_id="automatic")
    new_limits = bounds(max_calls=4, max_windows=4, max_frames=100)
    candidate = plan_windows(request, new_limits)
    assert candidate["fps"] != parent_plan["fps"]
    child = await execute_windows(candidate, new_limits, continuation_token="automatic")
    assert child["fps"] == parent["fps"] and child["plan_sha256"] == parent["plan_sha256"]
    assert child["status"] == "completed" and client.aio.models.generate_content.await_count == 3


@pytest.mark.parametrize("changes", [{"max_calls": 1}, {"max_windows": 1}, {"max_frames": 1}])
async def test_insufficient_initial_capacity_never_prepares_or_calls(scenario, changes):
    _, request, client = scenario
    limit = bounds(**changes)
    with patch(
        "video_research_mcp.video_window_run._video_file_content",
        side_effect=AssertionError("No preparation when already exhausted"),
    ):
        result = await execute_windows(plan_windows(request, limit), limit)
    assert result["status"] == "partial" and result["remaining_windows"] == [0, 1, 2]
    assert result["run_usage"]["provider_calls"] == 0
    client.aio.models.count_tokens.assert_not_awaited()
    client.aio.models.generate_content.assert_not_awaited()


async def test_post_count_token_exhaustion_keeps_known_unsent_window(scenario):
    _, request, client = scenario
    client.aio.models.count_tokens.return_value = types.CountTokensResponse(total_tokens=1000)
    limit = bounds(max_tokens=100, max_output_tokens=10)
    plan = plan_windows(request, limit)
    result = await execute_windows(plan, limit, job_id="counted")
    assert result["status"] == "partial" and result["continuation_token"] == "counted"
    assert result["remaining_windows"] == [0, 1, 2] and result["unknown_windows"] == []
    assert result["run_usage"]["provider_calls"] == result["run_usage"]["requested_windows"] == 1
    assert result["windows"][0]["execution_usage"]["calls"][0]["counted_input_tokens"] == 1000
    client.aio.models.generate_content.assert_not_awaited()
    client.aio.models.count_tokens.return_value = types.CountTokensResponse(total_tokens=3)
    child = await execute_windows(plan, bounds(), continuation_token="counted")
    assert child["status"] == "completed" and child["execution_usage"]["provider_calls"] == 7


async def test_direct_youtube_windows_continue_without_acquisition_or_upload(scenario):
    """GIVEN URL chunks WHEN continued THEN only canonical locator/settings are bound, no source SHA."""
    _, local, client = scenario
    request = WindowAnalysisRequest.model_validate(
        {
            **local.model_dump(),
            "file_path": None,
            "url": "https://youtu.be/dQw4w9WgXcQ?feature=fixture",
        }
    )
    first = bounds(max_calls=2, max_windows=2)
    plan = plan_windows(request, first)
    assert plan["source"]["kind"] == "remote_url" and plan["source"]["sha256"] is None
    assert plan["source"]["bytes"] is None and plan["source"]["freshness"] == "unknown"
    assert plan["preparation"]["local_read_bytes"] == 0
    with patch(
        "video_research_mcp.video_window_run._video_file_content",
        side_effect=AssertionError("URL mode never uploads/downloads"),
    ):
        parent = await execute_windows(plan, first, job_id="url-parent")
        child = await execute_windows(
            plan, bounds(max_calls=4, max_windows=4), continuation_token="url-parent"
        )
        await execute_windows(
            plan, bounds(max_calls=4, max_windows=4), continuation_token="url-parent"
        )
    assert parent["remaining_windows"] == [1, 2] and child["status"] == "completed"
    assert (
        client.aio.models.count_tokens.await_count
        == client.aio.models.generate_content.await_count
        == 3
    )
    for index, call in enumerate(client.aio.models.generate_content.call_args_list):
        media = call.kwargs["contents"].parts[0]
        assert media.file_data.file_uri == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert (
            media.media_processing == types.MediaProcessing.STATIC
            and media.video_metadata.fps == 2.0
        )
        assert (
            media.video_metadata.start_offset == f"{index * 400 // 1000}.{index * 400 % 1000:03d}s"
        )
    assert all(item["result"]["source_freshness"] == "unknown" for item in child["windows"])


async def test_source_mutation_rejected_before_any_provider_call(scenario):
    source, request, client = scenario
    plan = plan_windows(request, bounds())
    source.write_bytes(b"later user source change")
    with pytest.raises(ValueError, match="source changed"):
        await execute_windows(plan, bounds())
    client.aio.models.count_tokens.assert_not_awaited()
    client.aio.models.generate_content.assert_not_awaited()


async def test_changed_prepared_inline_payload_is_rejected_before_count(scenario):
    _, request, client = scenario
    plan = plan_windows(request, bounds())
    forged = types.Content(
        parts=[
            types.Part.from_bytes(data=b"forged", mime_type="video/mp4"),
            types.Part(text="instruction"),
        ]
    )
    with patch(
        "video_research_mcp.video_window_run._video_file_content",
        new=AsyncMock(return_value=(forged, plan["source"]["sha256"], "")),
    ):
        result = await execute_windows(plan, bounds())
    assert result["status"] == "partial" and result["continuation_token"] is None
    assert "Prepared inline bytes" in result["error"]["error"]
    client.aio.models.count_tokens.assert_not_awaited()


async def test_parallel_same_token_has_one_owner_and_no_extra_generation(scenario):
    _, request, client = scenario
    plan = plan_windows(request, bounds())
    await execute_windows(plan, bounds(max_calls=2, max_windows=2), job_id="parallel-parent")
    admitted, finish = asyncio.Event(), asyncio.Event()

    async def delayed(**kwargs):
        admitted.set()
        await asyncio.wait_for(finish.wait(), 5)
        return response()

    client.aio.models.generate_content.side_effect = delayed
    child_limits = bounds(max_calls=4, max_windows=4)
    first = asyncio.create_task(
        execute_windows(plan, child_limits, continuation_token="parallel-parent")
    )
    await asyncio.wait_for(admitted.wait(), 5)
    second = await execute_windows(plan, child_limits, continuation_token="parallel-parent")
    assert second["job_receipt"]["status"] == "running"
    finish.set()
    completed = await first
    assert (
        completed["status"] == "completed" and client.aio.models.generate_content.await_count == 3
    )


async def test_interrupted_generation_remains_unknown_and_never_resubmits(scenario):
    _, request, client = scenario
    plan = plan_windows(request, bounds())
    started = asyncio.Event()

    async def stopped(**kwargs):
        started.set()
        await asyncio.Future()

    client.aio.models.generate_content.side_effect = stopped
    task = asyncio.create_task(execute_windows(plan, bounds(), job_id="interrupted"))
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    retained = await execute_windows(plan, bounds(), job_id="interrupted")
    assert retained["status"] == "partial" and retained["unknown_windows"] == [0]
    assert retained["remaining_windows"] == [1, 2] and retained["continuation_token"] is None
    assert (
        retained["run_usage"]["provider_calls"] == 2
        and client.aio.models.generate_content.await_count == 1
    )


async def test_hard_killed_running_checkpoint_is_unknown_lower_bound(scenario):
    _, request, client = scenario
    plan = plan_windows(request, bounds())
    from video_research_mcp.video_window_run import _admit, _seed

    store = JobStore()
    job = _admit(store, plan, bounds(), "crashed", None)
    job = store.claim("crashed", "old-owner", lease_seconds=1, now=time.time() - 10)
    # Write under a controlled historical live lease, then let the real clock see it expired.
    state = _seed(job)
    state["windows"][0].update(status="running", run_job_id="crashed")
    assert store.checkpoint("crashed", "old-owner", result=state, now=time.time() - 10)
    result = await execute_windows(plan, bounds(), job_id="crashed")
    assert result["unknown_windows"] == result["unobserved_submissions"] == [0]
    assert result["remaining_windows"] == [1, 2] and not result["usage_complete"]
    assert "lower bounds" in result["counter_method"]
    client.aio.models.count_tokens.assert_not_awaited()


async def test_cancellation_before_first_count_preserves_all_pending_windows(scenario):
    _, request, client = scenario
    plan = plan_windows(request, bounds())
    from video_research_mcp.tools.video_file import _video_file_content

    async def canceled_after_prepare(*args, **kwargs):
        prepared = await _video_file_content(*args, **kwargs)
        JobStore().cancel("canceled-before")
        return prepared

    with patch(
        "video_research_mcp.video_window_run._video_file_content",
        side_effect=canceled_after_prepare,
    ):
        result = await execute_windows(plan, bounds(), job_id="canceled-before")
    assert result["status"] == "partial" and result["stop_reason"] == "cancel_requested"
    assert result["remaining_windows"] == [0, 1, 2] and result["continuation_token"] is None
    client.aio.models.count_tokens.assert_not_awaited()
    client.aio.models.generate_content.assert_not_awaited()


async def test_cancellation_during_count_blocks_generation_and_retains_known_unsent(scenario):
    """GIVEN a count callback cancels WHEN count returns THEN no generation is dispatched."""
    _, request, client = scenario

    async def canceled_count(**kwargs):
        JobStore().cancel("count-cancel")
        return types.CountTokensResponse(total_tokens=3)

    client.aio.models.count_tokens.side_effect = canceled_count
    result = await execute_windows(plan_windows(request, bounds()), bounds(), job_id="count-cancel")
    assert client.aio.models.count_tokens.await_count == 1
    client.aio.models.generate_content.assert_not_awaited()
    assert result["status"] == "partial" and result["stop_reason"] == "cancel_requested"
    assert result["remaining_windows"] == [0, 1, 2] and result["unknown_windows"] == []
    assert result["continuation_token"] is None and result["run_usage"]["provider_calls"] == 1
    item = result["windows"][0]
    assert item["status"] == "queued" and item["generation_dispatch"] == "not_sent"
    assert item["execution_usage"]["calls"][0]["counted_input_tokens"] == 3
    assert JobStore().get("count-cancel")["result"]["windows"][0] == item


async def test_lost_owner_during_count_preserves_fresh_canonical_row(scenario):
    """GIVEN count transfers a stale lease WHEN it returns THEN the former owner cannot send/write."""
    _, request, client = scenario
    store, captured = JobStore(), {}

    async def transferred_count(**kwargs):
        row = store.get("count-owner")
        fresh = store.claim("count-owner", "fresh-owner", now=row["lease_until"] + 1)
        assert fresh is not None
        captured["result"] = {**fresh["result"], "holder_marker": "fresh-owner-checkpoint"}
        assert store.checkpoint("count-owner", "fresh-owner", result=captured["result"])
        with store._connect() as db:
            captured["row"] = tuple(db.execute("SELECT * FROM jobs WHERE job_id=?", ("count-owner",)).fetchone())
        return types.CountTokensResponse(total_tokens=3)

    client.aio.models.count_tokens.side_effect = transferred_count
    result = await execute_windows(plan_windows(request, bounds()), bounds(), job_id="count-owner")
    assert client.aio.models.count_tokens.await_count == 1
    client.aio.models.generate_content.assert_not_awaited()
    assert result["job_receipt"]["status"] == "running"
    assert result["holder_marker"] == "fresh-owner-checkpoint"
    stopped = result["stopped_run"]
    assert stopped["reason"] == "ownership_lost" and stopped["provider_calls"] == 1
    assert stopped["window"]["status"] == "queued"
    assert stopped["window"]["generation_dispatch"] == "not_sent"
    assert stopped["window"]["execution_usage"]["calls"][0]["counted_input_tokens"] == 3
    with store._connect() as db:
        assert tuple(db.execute("SELECT * FROM jobs WHERE job_id=?", ("count-owner",)).fetchone()) == captured["row"]


async def test_late_completion_after_cancellation_is_explicit_partial(scenario):
    _, request, client = scenario
    plan = plan_windows(request, bounds())

    async def late(**kwargs):
        JobStore().cancel("late")
        return response()

    client.aio.models.generate_content.side_effect = late
    result = await execute_windows(plan, bounds(), job_id="late")
    assert (
        result["status"] == "partial" and result["windows"][0]["status"] == "completed_after_cancel"
    )
    assert result["windows"][0]["reconciliation_required"]
    assert result["remaining_windows"] == [1, 2] and result["continuation_token"] is None
    assert client.aio.models.generate_content.await_count == 1


async def test_continuation_changed_schema_or_runtime_cannot_send(scenario):
    _, request, client = scenario
    original = plan_windows(request, bounds())
    await execute_windows(original, bounds(max_calls=2, max_windows=2), job_id="binding-parent")
    changed = request.model_copy(
        update={"output_schema": {"type": "object", "properties": {"other": {"type": "string"}}}}
    )
    with pytest.raises(ValueError, match="schema/settings differ"):
        await execute_windows(
            plan_windows(changed, bounds()), bounds(), continuation_token="binding-parent"
        )
    from video_research_mcp.config import update_config

    update_config(default_temperature=0.123)
    with pytest.raises(ValueError, match="schema/settings differ"):
        await execute_windows(
            plan_windows(request, bounds()), bounds(), continuation_token="binding-parent"
        )
    assert client.aio.models.generate_content.await_count == 1


async def test_runtime_change_during_preparation_blocks_before_count(scenario):
    _, request, client = scenario
    plan = plan_windows(request, bounds())
    from video_research_mcp.config import update_config
    from video_research_mcp.tools.video_file import _video_file_content

    async def changed_settings(*args, **kwargs):
        result = await _video_file_content(*args, **kwargs)
        update_config(default_temperature=0.123)
        return result

    with patch(
        "video_research_mcp.video_window_run._video_file_content", side_effect=changed_settings
    ):
        result = await execute_windows(plan, bounds())
    assert result["status"] == "partial" and "settings changed" in result["error"]["error"]
    client.aio.models.count_tokens.assert_not_awaited()


async def test_corrupt_active_result_cannot_authorize_preparation(scenario):
    _, request, client = scenario
    plan = plan_windows(request, bounds())
    from video_research_mcp.video_window_run import _admit, _seed

    store = JobStore()
    job = _admit(store, plan, bounds(), "corrupt", None)
    store.claim("corrupt", "prior", lease_seconds=1, now=time.time() - 10)
    assert store.checkpoint("corrupt", "prior", result=_seed(job), now=time.time() - 10)
    with store._connect() as db:
        db.execute("UPDATE jobs SET result_json=? WHERE job_id='corrupt'", ('{"windows":[]}',))
    with pytest.raises(ValueError, match="readback attestation"):
        await execute_windows(plan, bounds(), job_id="corrupt")
    client.aio.models.count_tokens.assert_not_awaited()


async def test_remaining_output_allowance_is_capped_by_remaining_total_tokens(scenario):
    _, request, client = scenario
    limited = bounds(max_tokens=1200, max_output_tokens=1000)
    client.aio.models.generate_content.return_value.usage_metadata.prompt_token_count = 796
    client.aio.models.generate_content.return_value.usage_metadata.total_token_count = 800
    result = await execute_windows(plan_windows(request, limited), limited)
    assert result["status"] == "partial" and result["stop_reason"] == "budget_exhausted"
    assert result["windows"][1]["execution_usage"]["limits"]["max_output_tokens"] == 400
    assert result["remaining_windows"] == [1, 2] and result["run_usage"]["provider_calls"] == 3
    assert result["run_usage"]["reserved_or_reconciled_tokens"] == 800
    assert client.aio.models.generate_content.await_count == 1


@pytest.mark.parametrize(
    "kind",
    [
        "refusal",
        "truncated",
        "malformed",
        "usage_missing",
        "finish_missing",
        "output_usage_missing",
        "transport",
    ],
)
async def test_failed_refused_and_unknown_outcomes_never_become_complete(scenario, kind):
    _, request, client = scenario
    plan = plan_windows(request, bounds())
    if kind == "transport":
        client.aio.models.generate_content.side_effect = RuntimeError("503 unavailable")
    else:
        client.aio.models.generate_content.return_value = response(
            reason="SAFETY"
            if kind == "refusal"
            else "MAX_TOKENS"
            if kind == "truncated"
            else "STOP",
            usage=kind != "usage_missing",
            text="not JSON" if kind == "malformed" else '{"answer":"bounded"}',
        )
        if kind == "finish_missing":
            client.aio.models.generate_content.return_value.candidates[0].finish_reason = None
        if kind == "output_usage_missing":
            client.aio.models.generate_content.return_value.usage_metadata.candidates_token_count = None
    result = await execute_windows(plan, bounds(), job_id=kind)
    assert result["status"] == "partial" and result["continuation_token"] is None
    assert result["unresolved_windows"] == [0] and result["remaining_windows"] == [1, 2]
    assert (
        result["windows"][0]["status"]
        == {
            "refusal": "refused",
            "truncated": "failed",
            "malformed": "failed",
            "usage_missing": "unknown",
            "finish_missing": "unknown",
            "output_usage_missing": "unknown",
            "transport": "unknown",
        }[kind]
    )
    assert client.aio.models.generate_content.await_count == 1
    repeated = await execute_windows(plan, bounds(), job_id=kind)
    assert (
        repeated["unresolved_windows"] == [0]
        and client.aio.models.generate_content.await_count == 1
    )
