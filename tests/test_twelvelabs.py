"""Hosted workflow contracts under exact mocked response, account and restart controls."""

import asyncio
import json
from string import Formatter
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

import pytest

from video_research_mcp.config import update_config
from video_research_mcp.job_store import JobStore
from video_research_mcp.models.twelvelabs import TwelveLabsRequest
from video_research_mcp.search_provider_results import digest
from video_research_mcp.tools.twelvelabs import twelvelabs_call
from video_research_mcp.twelvelabs_routes import ROUTES

KEY = "twelvelabs-unit-secret-123456789"
VIDEO = {"type": "url", "url": "https://media.example/rights-owned.mp4"}


@pytest.fixture(autouse=True)
def service(monkeypatch, tmp_path):
    """Isolate credentials and durable state; no actual service account is selected."""
    update_config(twelvelabs_enabled=True)
    monkeypatch.setenv("TWELVELABS_API_KEY", KEY)
    monkeypatch.setenv("VRM_JOB_DB", str(tmp_path / "jobs.sqlite3"))


def request(operation, **overrides):
    """Select exact route IDs and an explicit bounded operation grant."""
    ids = {name: name + "A" for _, name, _, _ in Formatter().parse(ROUTES[operation][1]) if name}
    return TwelveLabsRequest.model_validate({"operation": operation, "ids": ids, "dry_run": False,
        "authorize_submission": True, "authorize_media_transfer": True, "authorize_destruction": True, **overrides})


def mock_exchange(monkeypatch, body, status=200):
    """Keep the boundary response bytes exact while retaining all dispatched options."""
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    mock = AsyncMock(return_value=(status, data))
    monkeypatch.setattr("video_research_mcp.twelvelabs_client.exchange", mock)
    return mock, data


def route_case(operation):
    """Concrete independent payload examples for every mapped current REST operation."""
    if operation == "asset_create":
        return {"url": VIDEO["url"]}, {"_id": "assetA", "status": "processing"}, 201
    if operation == "asset_get":
        return {}, {"_id": "asset_idA", "status": "ready"}, 200
    if operation == "index_create":
        return {"index_name": "operator-selected", "models": [{"model_name": "explicit-fixture-model", "model_options": ["visual"]}]}, {"_id": "indexA"}, 201
    if operation == "indexed_asset_create":
        return {"asset_id": "asset_idA"}, {"_id": "indexedA", "asset_id": "asset_idA"}, 202
    if operation == "indexed_asset_get":
        return {}, {"_id": "indexed_asset_idA", "asset_id": "assetA", "status": "ready"}, 200
    if operation == "search_text_image_composed_entity":
        return {"index_id": "indexA", "search_options": ["visual"], "query_text": "a <@entityA> near a sign"}, {"data": [{"video_id": "videoA", "start": 1.23456789, "end": 2.75, "rank": 1}], "search_pool": {"index_id": "indexA"}}, 200
    if operation == "embedding_task_create":
        return {"input_type": "video", "model_name": "explicit-fixture-model", "video": {"media_source": {"url": VIDEO["url"]}}}, {"_id": "taskA", "status": "processing", "data": None}, 200
    if operation == "embedding_task_get":
        return {}, {"_id": "task_idA", "status": "ready", "data": [{"embedding": [0.1, 0.2]}]}, 200
    if operation == "entity_collection_create":
        return {"name": "operator-collection"}, {"_id": "collectionA", "name": "operator-collection"}, 201
    if operation == "entity_create":
        return {"name": "operator-entity", "asset_ids": ["assetA"]}, {"_id": "entityA", "entity_collection_id": "collection_idA", "status": "processing"}, 201
    if operation == "analysis_sync":
        return {"video": VIDEO, "prompt": "Describe observable actions"}, {"id": "generationA", "data": "Provider description", "finish_reason": "stop", "usage": {"input_tokens": 4, "output_tokens": 3}}, 200
    if operation == "analysis_task_create":
        return {"video": VIDEO, "prompt": "Describe observable actions"}, {"task_id": "taskA", "status": "queued"}, 200
    if operation == "analysis_task_get":
        return {}, {"task_id": "task_idA", "status": "processing"}, 200
    if operation == "analysis_task_cancel":
        return {}, {"task_id": "task_idA", "status": "canceled"}, 200
    if operation.endswith("_delete"):
        return {}, b"", 204
    return {}, {"data": [], "page_info": {"total_page": 1}}, 200


@pytest.mark.parametrize("operation", list(ROUTES))
async def test_every_current_route_has_one_exact_attributed_operation(monkeypatch, operation):
    """GIVEN all 27 selected operations WHEN executed THEN IDs, wire route and bounds persist."""
    ready_id = None
    if operation == "indexed_asset_create":
        mock_exchange(monkeypatch, {"_id": "asset_idA", "status": "ready"})
        prior = await twelvelabs_call(request("asset_get", job_id="readyAsset"))
        ready_id = prior["job_receipt"]["job_id"]
    parameters, body, status = route_case(operation)
    mock, raw = mock_exchange(monkeypatch, body, status)
    result = await twelvelabs_call(request(operation, parameters=parameters, ready_asset_job_id=ready_id))
    assert "error" not in result, result
    assert mock.await_count == 1
    args, options = mock.await_args
    method, path, format_ = ROUTES[operation]
    assert urlsplit(args[0]).netloc == "api.twelvelabs.io"
    assert urlsplit(args[0]).path == path.format(**request(operation).ids)
    assert options["method"] == method and options["headers"]["x-api-key"] == KEY
    if format_ == "application/json":
        expected = {**parameters, "stream": False} if operation == "analysis_sync" else parameters
        assert json.loads(options["content"]) == expected
    assert result["provider_response_sha256"] == digest(raw)
    assert result["source_verified_truth"] is False and result["entity_identity_verified"] is False
    assert result["external_mcp_discovery_verified"] is False
    assert result["execution"]["provider_requests_attempted"] == 1
    assert result["execution"]["cost_usd"] is None
    assert result["job_receipt"]["attestation"]["verified"]
    assert result["job_receipt"]["status"] == "completed"
    if operation == "search_text_image_composed_entity":
        assert result["clips"][0]["start"] == 1.23456789
        assert result["clips"][0]["video_id"] == "videoA"
        assert result["clips"][0]["provider_reference"].endswith("#t=1.23456789,2.75")
        assert result["clips"][0]["source_bytes_verified"] is False


@pytest.mark.parametrize("provider_status,extra,expected", [
    ("queued", {}, "processing"), ("pending", {}, "processing"), ("processing", {}, "processing"),
    ("ready", {"result": {"data": "answer", "finish_reason": "stop"}}, "ready"),
    ("ready", {"result": {"data": "partial", "finish_reason": "length"}, "error": {"code": "truncated"}}, "partial"),
    ("ready", {}, "unknown"), ("failed", {"error": {"code": "failed"}}, "failed"),
    ("canceled", {}, "canceled"), ("new_state", {}, "unknown"),
])
async def test_remote_status_never_promotes_polling_or_partial_output(monkeypatch, provider_status, extra, expected):
    mock_exchange(monkeypatch, {"task_id": "task_idA", "status": provider_status, **extra})
    result = await twelvelabs_call(request("analysis_task_get"))
    assert result["status"] == expected
    assert result["provider_status"] == provider_status
    assert result["provider_data"] == {"task_id": "task_idA", "status": provider_status, **extra}
    assert result["execution"]["calls"][0]["usage"] is None


async def test_restart_replay_and_changed_bindings_never_resubmit(monkeypatch):
    mock, _ = mock_exchange(monkeypatch, {"task_id": "taskA", "status": "processing"})
    selected = request("analysis_task_create", parameters={"video": VIDEO}, job_id="repeat")
    first = await twelvelabs_call(selected)
    second = await twelvelabs_call(selected)
    assert {k: v for k, v in first.items() if k != "job_receipt"} == {k: v for k, v in second.items() if k != "job_receipt"}
    assert first["job_receipt"]["result_sha256"] == second["job_receipt"]["result_sha256"]
    assert second["job_receipt"]["attestation"]["verified"] and mock.await_count == 1
    different = await twelvelabs_call(selected.model_copy(update={"parameters": {"video": VIDEO, "prompt": "changed"}}))
    assert "error" in different and mock.await_count == 1
    monkeypatch.setenv("TWELVELABS_API_KEY", "different-twelvelabs-unit-account")
    changed_account = await twelvelabs_call(selected)
    assert "error" in changed_account and mock.await_count == 1


async def test_interruption_is_retained_and_replay_cannot_repeat_unknown_submission(monkeypatch):
    mock = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr("video_research_mcp.twelvelabs_client.exchange", mock)
    selected = request("analysis_task_create", parameters={"video": VIDEO}, job_id="interrupted")
    first = await twelvelabs_call(selected)
    assert first["category"] == "CANCELLED"
    assert first["execution"]["physical_requests"] is None
    assert first["job_receipt"]["status"] == "unknown"
    assert first["job_receipt"]["attestation"]["verified"]
    replay = await twelvelabs_call(selected)
    assert {k: v for k, v in first.items() if k != "job_receipt"} == {k: v for k, v in replay.items() if k != "job_receipt"}
    assert first["job_receipt"]["result_sha256"] == replay["job_receipt"]["result_sha256"]
    assert replay["job_receipt"]["attestation"]["verified"] and mock.await_count == 1


async def test_observation_during_inflight_call_reads_reservation_without_resending(monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()

    async def blocked(*args, **kwargs):
        started.set()
        await release.wait()
        return 200, b'{"task_id":"taskA","status":"processing"}'

    mock = AsyncMock(side_effect=blocked)
    monkeypatch.setattr("video_research_mcp.twelvelabs_client.exchange", mock)
    selected = request("analysis_task_create", parameters={"video": VIDEO}, job_id="reserved")
    running = asyncio.create_task(twelvelabs_call(selected))
    await started.wait()
    retained = await twelvelabs_call(selected)
    assert retained["error"] == "call_reserved_outcome_unknown"
    assert retained["execution"]["physical_request_upper_bound"] == 1
    assert mock.await_count == 1
    release.set()
    assert (await running)["status"] == "processing"


async def test_source_account_switch_refuses_result_but_preserves_attempt_hash(monkeypatch):
    async def changed(*args, **kwargs):
        update_config(twelvelabs_enabled=False)
        return 200, b'{"task_id":"taskA","status":"ready"}'

    mock = AsyncMock(side_effect=changed)
    monkeypatch.setattr("video_research_mcp.twelvelabs_client.exchange", mock)
    result = await twelvelabs_call(request("analysis_task_create", parameters={"video": VIDEO}))
    assert result["category"] == "PERMISSION_DENIED"
    assert result["execution"]["calls"][0]["response_sha256"]
    assert result["job_receipt"]["status"] == "unknown"
    assert "provider_data" not in result


async def test_corrupt_storage_is_rejected_without_a_second_http_request(monkeypatch):
    mock, _ = mock_exchange(monkeypatch, {"data": []})
    selected = request("asset_list", job_id="corrupted")
    await twelvelabs_call(selected)
    store = JobStore()
    with store._connect() as db:
        db.execute("UPDATE jobs SET result_json=? WHERE job_id=?", ('{"changed":true}', "corrupted"))
    result = await twelvelabs_call(selected)
    assert "error" in result and mock.await_count == 1


async def test_shared_privacy_source_revision_cannot_replay_an_older_observation(monkeypatch):
    """GIVEN an attested receipt WHEN shared normalization source changes THEN refuse stale replay."""
    from pathlib import Path

    mock, _ = mock_exchange(monkeypatch, {"data": []})
    selected = request("asset_list", job_id="source-bound")
    assert (await twelvelabs_call(selected))["status"] == "complete"
    read_bytes = Path.read_bytes

    def changed_source(path):
        data = read_bytes(path)
        return data + b"\n# controlled source revision\n" if path.name == "search_provider_results.py" else data

    monkeypatch.setattr(Path, "read_bytes", changed_source)
    result = await twelvelabs_call(selected)
    assert "error" in result and mock.await_count == 1
