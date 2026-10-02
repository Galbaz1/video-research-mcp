"""Authority, data admission and malformed response controls for hosted operations."""

import asyncio
import json
import os
import threading
from unittest.mock import AsyncMock

import pytest

from video_research_mcp.config import update_config
from video_research_mcp.provider_readiness import optional_adapter_profiles
from video_research_mcp.search_provider_results import digest
from video_research_mcp.tools.twelvelabs import twelvelabs_call

KEY = "twelvelabs-bound-secret-123456789"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    update_config(twelvelabs_enabled=True, local_file_access_root=str(tmp_path))
    monkeypatch.setenv("TWELVELABS_API_KEY", KEY)
    monkeypatch.setenv("VRM_JOB_DB", str(tmp_path / "jobs.sqlite3"))


def chosen(**overrides):
    return {"operation": "asset_list", "dry_run": False, "authorize_submission": True, **overrides}


@pytest.mark.parametrize("mode", ["dry", "disabled", "key_missing", "key_placeholder", "grant_missing"])
async def test_inert_states_have_no_http_and_no_database(monkeypatch, tmp_path, mode):
    mock = AsyncMock()
    monkeypatch.setattr("video_research_mcp.twelvelabs_client.exchange", mock)
    options = chosen()
    if mode == "dry":
        options["dry_run"] = True
    elif mode == "disabled":
        update_config(twelvelabs_enabled=False)
    elif mode == "key_missing":
        monkeypatch.delenv("TWELVELABS_API_KEY")
    elif mode == "key_placeholder":
        monkeypatch.setenv("TWELVELABS_API_KEY", "${MISSING_KEY}")
    else:
        options["authorize_submission"] = False
    result = await twelvelabs_call(options)
    assert result.get("status") == "planned" if mode == "dry" else result["category"] == "PERMISSION_DENIED"
    assert not mock.called and not (tmp_path / "jobs.sqlite3").exists()


@pytest.mark.parametrize("operation,ids,parameters,grant", [
    ("asset_create", {}, {"url": "https://media.example/a.mp4"}, "authorize_media_transfer"),
    ("analysis_task_create", {}, {"video": {"type": "url", "url": "https://media.example/a.mp4"}}, "authorize_media_transfer"),
    ("asset_delete", {"asset_id": "assetA"}, {}, "authorize_destruction"),
    ("analysis_task_cancel", {"task_id": "taskA"}, {}, "authorize_destruction"),
])
async def test_media_and_destruction_have_separate_grants(monkeypatch, operation, ids, parameters, grant):
    mock = AsyncMock()
    monkeypatch.setattr("video_research_mcp.twelvelabs_client.exchange", mock)
    result = await twelvelabs_call(chosen(operation=operation, ids=ids, parameters=parameters,
        authorize_media_transfer=grant != "authorize_media_transfer", authorize_destruction=grant != "authorize_destruction"))
    assert result["category"] == "PERMISSION_DENIED" and not mock.called


@pytest.mark.parametrize("overrides", [
    {"ids": {"asset_id": "../secret"}}, {"ids": {"asset_id": "extra"}}, {"operation": "not_a_route"},
    {"parameters": {"page_limit": 51}}, {"parameters": {"page_limit": True}},
    {"parameters": {"a": "x" * (64 * 1024)}}, {"parameters": {"NaN": float("nan")}},
    {"operation": "asset_create", "parameters": {"url": "http://127.0.0.1/private"}},
    {"operation": "asset_create", "parameters": {"url": ["https://media.example/a.mp4"]}},
    {"operation": "analysis_sync", "parameters": {"video": {"type": "url", "url": "https://media.example/a.mp4"}, "stream": True}},
    {"operation": "analysis_sync", "parameters": {"video": {"type": "url", "url": "https://media.example/a.mp4"}, "start_time": 1, "end_time": 1.5}},
    {"operation": "embedding_task_create", "parameters": {"input_type": "video", "model_name": "operator-model", "video": {"media_source": {"type": "url", "url": "https://media.example/a.mp4"}}}},
    {"parameters": {"file": "/private/source"}}, {"parameters": {"legacy": ["x"] * 129}},
    {"parameters": {"secret": KEY}},
])
async def test_invalid_input_refuses_before_http(monkeypatch, overrides):
    mock = AsyncMock()
    monkeypatch.setattr("video_research_mcp.twelvelabs_client.exchange", mock)
    result = await twelvelabs_call(chosen(authorize_media_transfer=True, **overrides))
    assert "error" in result and not mock.called
    assert KEY not in json.dumps(result)


async def test_fenced_media_hash_is_exact_and_private_filename_is_not_sent(monkeypatch, tmp_path):
    path = tmp_path / "private-client-name.png"
    path.write_bytes(b"bounded fixture image bytes")
    mock = AsyncMock(return_value=(201, b'{"_id":"assetA","status":"processing"}'))
    monkeypatch.setattr("video_research_mcp.twelvelabs_client.exchange", mock)
    result = await twelvelabs_call(chosen(operation="asset_create", local_file=str(path),
        expected_source_sha256=digest(path.read_bytes()), authorize_media_transfer=True))
    assert result["status"] == "processing"
    wire = mock.await_args.kwargs["content"]
    assert path.read_bytes() in wire and b'filename="media.png"' in wire
    assert b"image/png" in wire and b"private-client-name" not in wire
    assert result["media"]["admission_bytes_verified"] is True
    assert result["media"]["decoded_media_verified"] is False
    assert result["media"]["remote_bytes_verified"] is False


@pytest.mark.parametrize("case", ["hash", "size", "fifo", "outside", "video_query", "symlink"])
async def test_bad_local_media_is_refused_with_no_transport(monkeypatch, tmp_path, case):
    path = tmp_path / "fixture.png"
    path.write_bytes(b"bytes")
    options = chosen(operation="asset_create", local_file=str(path),
        expected_source_sha256=digest(b"bytes"), authorize_media_transfer=True)
    if case == "hash":
        options["expected_source_sha256"] = "0" * 64
    elif case == "size":
        options["max_media_bytes"] = 1
    elif case == "fifo":
        path.unlink()
        os.mkfifo(path)
    elif case == "outside":
        update_config(local_file_access_root=str(tmp_path / "another-root"))
    elif case == "video_query":
        video = tmp_path / "fixture.mp4"
        path.rename(video)
        options.update(operation="search_text_image_composed_entity", local_file=str(video),
            parameters={"index_id": "indexA", "search_options": ["visual"]})
    else:
        target = tmp_path / "actual.png"
        path.rename(target)
        path.symlink_to(target)
    mock = AsyncMock()
    monkeypatch.setattr("video_research_mcp.twelvelabs_client.exchange", mock)
    result = await asyncio.wait_for(twelvelabs_call(options), 2)
    assert "error" in result and not mock.called


@pytest.mark.parametrize("body,status,expected", [
    (b'{"_id":"otherAsset","status":"ready"}', 200, "provider_identity_conflict"),
    (b"not JSON", 200, "invalid_twelvelabs_operation"),
    (b'{"_id":"asset_idA","data":NaN}', 200, "nonfinite_json"),
    (b'{"_id":"asset_idA","data":1e309}', 200, "invalid_twelvelabs_operation"),
    (b"", 200, "empty_provider_response"),
    (b'{"secret":"upstream-body-withheld"}', 401, "provider_http_401"),
    (b'{"error":"quota"}', 429, "provider_http_429"),
])
async def test_failed_responses_keep_attempt_and_raw_hash(monkeypatch, body, status, expected):
    mock = AsyncMock(return_value=(status, body))
    monkeypatch.setattr("video_research_mcp.twelvelabs_client.exchange", mock)
    result = await twelvelabs_call(chosen(operation="asset_get", ids={"asset_id": "asset_idA"}))
    assert result["error"] == expected
    assert result["execution"]["calls"][0]["response_sha256"] == digest(body)
    assert "upstream-body-withheld" not in json.dumps(result)
    assert mock.await_count == 1 and result["job_receipt"]["status"] == "unknown"


async def test_partial_search_preserves_rejected_denominator_and_provider_bytes(monkeypatch):
    body = {"data": [{"video_id": "videoA", "start": 0.25, "end": 1.125},
                     {"video_id": "bad", "start": 2, "end": 1}]}
    raw = json.dumps(body).encode()
    mock = AsyncMock(return_value=(200, raw))
    monkeypatch.setattr("video_research_mcp.twelvelabs_client.exchange", mock)
    result = await twelvelabs_call(chosen(operation="search_text_image_composed_entity",
        parameters={"index_id": "indexA", "search_options": ["visual"], "query_text": "sign"}))
    assert result["status"] == "partial" and len(result["clips"]) == 1
    assert result["rejections"] == [{"index": 1, "code": "malformed_provider_clip"}]
    assert result["provider_data"] == body and result["provider_response_sha256"] == digest(raw)


async def test_secret_echo_redacted_response_hash_keeps_original_bytes(monkeypatch):
    raw = json.dumps({"data": [], "note": "prefix" + KEY + "suffix"}).encode()
    monkeypatch.setattr("video_research_mcp.twelvelabs_client.exchange", AsyncMock(return_value=(200, raw)))
    result = await twelvelabs_call(chosen())
    assert KEY not in json.dumps(result)
    assert result["provider_response_sha256"] == digest(raw)
    assert result["provider_data"]["note"] == "prefix[redacted]suffix"


@pytest.mark.parametrize("encode", [lambda s: s.replace("-", "%2D"), lambda s: "".join(f"%{b:02x}" for b in s.encode())])
async def test_partially_or_fully_percent_encoded_secret_echo_is_withheld(monkeypatch, encode):
    raw = json.dumps({"data": [], "encoded": "prefix" + encode(KEY) + "suffix"}).encode()
    monkeypatch.setattr("video_research_mcp.twelvelabs_client.exchange", AsyncMock(return_value=(200, raw)))
    result = await twelvelabs_call(chosen())
    assert result["provider_data"]["encoded"] == "[redacted]"
    assert result["provider_response_sha256"] == digest(raw)
    assert result["job_receipt"]["attestation"]["verified"]


@pytest.mark.parametrize("limit", ["max_response_bytes", "max_text_bytes"])
async def test_smaller_response_limits_refuse_without_truncating(monkeypatch, limit):
    raw = b'{"data":[],"text":"too long"}'
    mock = AsyncMock(return_value=(200, raw))
    monkeypatch.setattr("video_research_mcp.twelvelabs_client.exchange", mock)
    result = await twelvelabs_call(chosen(**{limit: 3}))
    assert "error" in result and mock.await_count == 1
    assert result["execution"]["calls"][0]["response_sha256"] == digest(raw)


@pytest.mark.parametrize("case", ["missing", "processing", "different_id", "different_account"])
async def test_indexing_requires_attested_matching_ready_asset_without_implicit_get(monkeypatch, case):
    mock = AsyncMock(return_value=(200, json.dumps({"_id": "assetA", "status": "processing" if case == "processing" else "ready"}).encode()))
    monkeypatch.setattr("video_research_mcp.twelvelabs_client.exchange", mock)
    ready = await twelvelabs_call(chosen(operation="asset_get", ids={"asset_id": "assetA"}, job_id="prior"))
    if case == "different_account":
        monkeypatch.setenv("TWELVELABS_API_KEY", "other-twelvelabs-account")
    result = await twelvelabs_call(chosen(operation="indexed_asset_create", ids={"index_id": "indexA"},
        parameters={"asset_id": "otherAsset" if case == "different_id" else "assetA"},
        ready_asset_job_id=None if case == "missing" else ready["job_receipt"]["job_id"], authorize_media_transfer=True))
    assert "error" in result and mock.await_count == 1


def test_readiness_is_read_only_and_makes_no_live_discovery_claim():
    disabled = optional_adapter_profiles({})["twelvelabs"]
    enabled = optional_adapter_profiles({"TWELVELABS_ENABLED": "true", "TWELVELABS_API_KEY": KEY})["twelvelabs"]
    assert disabled["state"] == "disabled"
    assert enabled["state"] == "configured-but-unverified"
    assert enabled["external_mcp_discovery_verified"] is False


@pytest.mark.parametrize("mode", ["cancel", "deadline"])
async def test_preparation_worker_is_joined_before_cancellation_or_timeout_returns(monkeypatch, tmp_path, mode):
    """GIVEN a live admitted read WHEN interrupted THEN its actual stream closes before return."""
    from video_research_mcp import twelvelabs_payloads

    path = tmp_path / "owned.png"
    path.write_bytes(b"owned bytes")
    started, release, closed = threading.Event(), threading.Event(), threading.Event()
    original_open = twelvelabs_payloads._open_regular

    class BlockedRead:
        def __enter__(self):
            self.stream = original_open(path)
            return self

        def read(self, size):
            started.set()
            assert release.wait(2), "Bounded control must release its actual read"
            return self.stream.read(size)

        def __exit__(self, *args):
            self.stream.close()
            closed.set()

    monkeypatch.setattr(twelvelabs_payloads, "_open_regular", lambda p: BlockedRead())
    mock = AsyncMock()
    monkeypatch.setattr("video_research_mcp.twelvelabs_client.exchange", mock)
    operation = asyncio.create_task(twelvelabs_call(chosen(operation="asset_create", dry_run=True,
        local_file=str(path), expected_source_sha256=digest(path.read_bytes()), timeout_seconds=0.05 if mode == "deadline" else 1)))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        if mode == "cancel":
            operation.cancel()
            await asyncio.sleep(0.02)
            operation.cancel()
        await asyncio.sleep(0.08)
        assert not operation.done() and not closed.is_set()
    finally:
        release.set()
    result = await asyncio.wait_for(operation, 1)
    assert closed.is_set() and not mock.called
    assert result["category"] == ("CANCELLED" if mode == "cancel" else "NETWORK_ERROR")
    assert result["execution"]["provider_requests_attempted"] == 0
    assert not (tmp_path / "jobs.sqlite3").exists()
