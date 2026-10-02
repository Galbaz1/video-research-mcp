"""File API recovery and exact source/account reservations using real temp SQLite."""

import asyncio
import hashlib
import json
import os
import sqlite3
from unittest.mock import AsyncMock

import httpx
import pytest
from google import genai
from google.genai import errors, types

from video_research_mcp.job_store import JobStore
from video_research_mcp.tools import video_file, video_upload
from video_research_mcp.tools.video_file import _upload_large_file


def provider_file(name="one", state="ACTIVE", **kwargs):
    return types.File(uri=f"https://api.example/files/{name}", name=f"files/{name}",
                      state=state, **kwargs)


@pytest.fixture
def upload_case(tmp_path, mock_gemini_client):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"owned media")
    client = mock_gemini_client["client"]
    uploaded = provider_file(state="PROCESSING")
    client.aio.files.upload = AsyncMock(return_value=uploaded)
    client.aio.files.get = AsyncMock(return_value=provider_file())
    return source, client, uploaded


def receipt(source):
    return video_file._load_upload_cache(video_file._file_content_hash(source))


async def test_processing_timeout_separate_call_reuses_known_upload(upload_case, monkeypatch):
    source, client, uploaded = upload_case
    waiter = AsyncMock(side_effect=[TimeoutError("processing"), None])
    monkeypatch.setattr(video_file, "_wait_for_active", waiter)
    digest = video_file._file_content_hash(source)
    with pytest.raises(TimeoutError):
        await _upload_large_file(source, "video/mp4", digest)
    retained = receipt(source)
    assert retained["file_name"] == uploaded.name
    assert retained["status"] == "unknown" and retained["owner"] is None
    assert await _upload_large_file(source, "video/mp4", digest) == uploaded.uri
    assert client.aio.files.upload.await_count == 1
    assert receipt(source)["provider_state"] == "ACTIVE"
    assert all(call.kwargs["expected_uri"] == uploaded.uri for call in waiter.await_args_list)


async def test_cache_miss_saves_scoped_attested_resource_and_preserves_source(upload_case):
    source, client, uploaded = upload_case
    before = source.read_bytes()
    assert await _upload_large_file(source, "video/mp4") == uploaded.uri
    cached = receipt(source)
    assert cached["file_uri"] == uploaded.uri and cached["file_name"] == uploaded.name
    assert cached["upload_attempts"] == cached["poll_attempts"] == 1
    assert cached["wire_attempts"] is None and cached["owner"] is None
    assert cached["attestation"]["request_integrity"] == "verified"
    assert cached["attestation"]["result_integrity"] == "verified"
    row = JobStore().get(cached["job_id"])
    assert row["source_revision"] == hashlib.sha256(before).hexdigest()
    assert row["request"]["source_bytes"] == len(before)
    assert source.read_bytes() == before
    index = next(video_file._upload_cache_dir().glob("*.json"))
    assert index.stat().st_mode & 0o777 == 0o600
    assert "test-key-not-real" not in index.read_text()
    assert "test-key-not-real" not in json.dumps(row)
    assert client.aio.files.upload.call_args.kwargs["file"].closed


async def test_active_resource_cache_hit_polls_without_upload(upload_case):
    source, client, uploaded = upload_case
    assert await _upload_large_file(source, "video/mp4") == uploaded.uri
    assert await _upload_large_file(source, "video/mp4") == uploaded.uri
    assert client.aio.files.upload.await_count == 1
    assert client.aio.files.get.await_count == 2
    assert receipt(source)["poll_attempts"] == 2


@pytest.mark.parametrize("unavailable", ["FAILED", "404"])
async def test_known_unavailable_resource_allows_new_upload(upload_case, unavailable):
    source, client, _ = upload_case
    await _upload_large_file(source, "video/mp4")
    first_id = receipt(source)["job_id"]
    failure = provider_file(state="FAILED") if unavailable == "FAILED" else errors.ClientError(
        404, {"error": {"message": "fixture absent", "status": "NOT_FOUND"}})
    client.aio.files.get.side_effect = [failure, provider_file("new")]
    client.aio.files.upload.return_value = types.File(
        uri="https://api.example/files/new", name="files/new", state="PROCESSING")
    assert await _upload_large_file(source, "video/mp4") == "https://api.example/files/new"
    assert client.aio.files.upload.await_count == 2
    old = JobStore().get(first_id)
    assert old["status"] == "failed" and old["owner"] is None
    assert old["result"]["provider_state"] == ("FAILED" if unavailable == "FAILED" else "NOT_FOUND")


async def test_fresh_failed_resource_does_not_retry_in_same_call(upload_case):
    source, client, _ = upload_case
    client.aio.files.get.return_value = provider_file(state="FAILED")
    with pytest.raises(video_upload.FileUnavailable):
        await _upload_large_file(source, "video/mp4")
    assert client.aio.files.upload.await_count == 1


async def test_unknown_upload_exception_blocks_resubmission(upload_case):
    source, client, _ = upload_case
    client.aio.files.upload.side_effect = ConnectionError("fixture-secret transport")
    with pytest.raises(ConnectionError):
        await _upload_large_file(source, "video/mp4")
    with pytest.raises(RuntimeError, match="refusing duplicate"):
        await _upload_large_file(source, "video/mp4")
    assert client.aio.files.upload.await_count == 1
    row = JobStore().get(receipt(source)["job_id"])
    assert row["status"] == "unknown" and row["external_id"] is None
    assert "fixture-secret" not in json.dumps(row)


@pytest.mark.parametrize("failure", [TimeoutError("fixture"), RuntimeError("unknown"),
                                     errors.ClientError(403, {"error": {"message": "denied"}})])
async def test_unknown_poll_preserves_identity_and_never_reuploads(upload_case, failure):
    source, client, uploaded = upload_case
    client.aio.files.get.side_effect = [failure, provider_file()]
    with pytest.raises(type(failure)):
        await _upload_large_file(source, "video/mp4")
    assert receipt(source)["file_uri"] == uploaded.uri
    assert await _upload_large_file(source, "video/mp4") == uploaded.uri
    assert client.aio.files.upload.await_count == 1


async def test_source_and_account_changes_cannot_reuse_other_resource(upload_case, monkeypatch, clean_config):
    source, client, _ = upload_case
    client.aio.files.upload.side_effect = [
        types.File(uri=f"https://api.example/files/id{i}", name=f"files/id{i}", state="ACTIVE")
        for i in range(3)]
    client.aio.files.get.side_effect = [provider_file(f"id{i}") for i in range(3)]
    first = await _upload_large_file(source, "video/mp4")
    source.write_bytes(b"different source")
    second = await _upload_large_file(source, "video/mp4")
    monkeypatch.setenv("GEMINI_API_KEY", "other-test-account")
    from video_research_mcp.config import update_config
    update_config(gemini_api_key="other-test-account")
    third = await _upload_large_file(source, "video/mp4")
    assert len({first, second, third}) == 3 and client.aio.files.upload.await_count == 3
    assert len(list(video_file._upload_cache_dir().glob("*.json"))) == 3


async def test_account_scoped_external_identity_supports_same_name(upload_case, monkeypatch, clean_config):
    source, client, uploaded = upload_case
    await _upload_large_file(source, "video/mp4")
    monkeypatch.setenv("GEMINI_API_KEY", "other-test-account")
    from video_research_mcp.config import update_config
    update_config(gemini_api_key="other-test-account")
    assert await _upload_large_file(source, "video/mp4") == uploaded.uri
    assert client.aio.files.upload.await_count == 2


async def test_concurrent_same_source_coalesces_one_upload(upload_case):
    source, client, uploaded = upload_case
    async def slow_upload(**kwargs):
        await asyncio.sleep(0.02)
        return uploaded
    client.aio.files.upload.side_effect = slow_upload
    assert await asyncio.gather(*[_upload_large_file(source, "video/mp4") for _ in range(2)]) == [uploaded.uri] * 2
    assert client.aio.files.upload.await_count == 1


async def test_existing_canonical_lease_blocks_independent_worker(upload_case):
    source, client, _ = upload_case
    await _upload_large_file(source, "video/mp4")
    row = JobStore().claim(receipt(source)["job_id"], "another-worker")
    assert row is not None
    with pytest.raises(RuntimeError, match="another worker"):
        await _upload_large_file(source, "video/mp4")
    assert client.aio.files.upload.await_count == 1


async def test_cancel_unknown_upload_joins_owned_cleanup_preserves_original(upload_case):
    source, client, _ = upload_case
    entered = asyncio.Event()
    before = source.read_bytes()
    async def pending_upload(**kwargs):
        entered.set()
        await asyncio.Event().wait()
    client.aio.files.upload.side_effect = pending_upload
    task = asyncio.create_task(_upload_large_file(source, "video/mp4"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert source.read_bytes() == before
    assert client.aio.files.upload.call_args.kwargs["file"].closed
    with pytest.raises(RuntimeError, match="refusing duplicate"):
        await _upload_large_file(source, "video/mp4")
    assert receipt(source)["owner"] is None


async def test_source_changed_during_upload_rejects_return_and_keeps_owned_bytes(upload_case):
    source, client, uploaded = upload_case
    before = source.read_bytes()
    seen = []
    async def mutate_source(**kwargs):
        seen.append(kwargs["file"].read())
        source.write_bytes(b"changed source")
        return uploaded
    client.aio.files.upload.side_effect = mutate_source
    with pytest.raises(ValueError, match="changed during"):
        await _upload_large_file(source, "video/mp4")
    assert seen == [before] and source.read_bytes() == b"changed source"


@pytest.mark.parametrize("damage", ["corrupt", "large", "symlink", "fifo"])
async def test_cache_index_damage_fails_closed_without_provider(upload_case, damage):
    source, client, _ = upload_case
    await _upload_large_file(source, "video/mp4")
    index = next(video_file._upload_cache_dir().glob("*.json"))
    index.unlink()
    if damage == "symlink":
        index.symlink_to(source)
    elif damage == "fifo":
        os.mkfifo(index)
    else:
        index.write_bytes(b"{" if damage == "corrupt" else b"x" * 8193)
    with pytest.raises((PermissionError, ValueError)):
        await _upload_large_file(source, "video/mp4")
    assert client.aio.files.upload.await_count == client.aio.files.get.await_count == 1


async def test_missing_index_recovers_active_resource_not_duplicate(upload_case):
    source, client, uploaded = upload_case
    await _upload_large_file(source, "video/mp4")
    next(video_file._upload_cache_dir().glob("*.json")).unlink()
    assert await _upload_large_file(source, "video/mp4") == uploaded.uri
    assert client.aio.files.upload.await_count == 1


async def test_corrupted_canonical_request_fails_before_provider(upload_case):
    source, client, _ = upload_case
    await _upload_large_file(source, "video/mp4")
    job_id = receipt(source)["job_id"]
    with sqlite3.connect(os.environ["VRM_JOB_DB"]) as db:
        db.execute("UPDATE jobs SET source_revision='corrupt' WHERE job_id=?", (job_id,))
    with pytest.raises(ValueError, match="integrity"):
        await _upload_large_file(source, "video/mp4")
    assert client.aio.files.upload.await_count == client.aio.files.get.await_count == 1


async def test_wrong_source_commitment_fails_before_provider(upload_case):
    source, client, _ = upload_case
    with pytest.raises(ValueError, match="Source SHA256 differs"):
        await _upload_large_file(source, "video/mp4", "0" * 64)
    client.aio.files.upload.assert_not_called()


async def test_generic_pdf_entry_point_keeps_complete_identity(upload_case):
    source, client, uploaded = upload_case
    pdf = source.with_suffix(".pdf")
    pdf.write_bytes(b"%PDF-1.4 owned original")
    assert await _upload_large_file(pdf, "application/pdf") == uploaded.uri
    assert client.aio.files.upload.call_args.kwargs["config"].mime_type == "application/pdf"


async def test_actual_sdk_upload_503_is_one_wire_attempt_and_unknown_reservation(upload_case, monkeypatch):
    source, _, _ = upload_case
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(503, json={"error": {"message": "fixture failure", "status": "UNAVAILABLE"}})
    transport = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    client = genai.Client(api_key="fixture-key", http_options=types.HttpOptions(
        httpx_async_client=transport, retry_options=types.HttpRetryOptions(attempts=1)))
    monkeypatch.setattr(video_upload.GeminiClient, "get", lambda: client)
    try:
        with pytest.raises(errors.ServerError):
            await _upload_large_file(source, "video/mp4")
        with pytest.raises(RuntimeError, match="refusing duplicate"):
            await _upload_large_file(source, "video/mp4")
    finally:
        await client.aio.aclose()
    assert len(requests) == 1 and requests[0].method == "POST"
    assert receipt(source)["wire_attempts"] is None


async def test_file_api_calls_are_bounded_and_directory_modes_preserved(upload_case):
    source, client, _ = upload_case
    directory = video_file._upload_cache_dir()
    directory.chmod(0o750)
    await _upload_large_file(source, "video/mp4")
    assert directory.stat().st_mode & 0o777 == 0o750
    for call in [client.aio.files.upload.call_args, client.aio.files.get.call_args]:
        options = call.kwargs["config"].http_options
        assert 0 < options.timeout <= 120000 and options.retry_options.attempts == 1


async def test_expired_known_resource_allows_one_new_upload(upload_case):
    from datetime import datetime, timezone
    source, client, _ = upload_case
    await _upload_large_file(source, "video/mp4")
    job_id = receipt(source)["job_id"]
    client.aio.files.get.side_effect = [
        provider_file(expiration_time=datetime(2000, 1, 1, tzinfo=timezone.utc)),
        provider_file("replacement")]
    client.aio.files.upload.return_value = types.File(
        uri="https://api.example/files/replacement", name="files/replacement", state="ACTIVE")
    assert await _upload_large_file(source, "video/mp4") == "https://api.example/files/replacement"
    assert JobStore().get(job_id)["result"]["provider_state"] == "EXPIRED"
    assert client.aio.files.upload.await_count == 2


async def test_cancel_known_poll_retains_identity_for_separate_call(upload_case):
    source, client, uploaded = upload_case
    entered = asyncio.Event()
    async def pending_poll(**kwargs):
        entered.set()
        await asyncio.Event().wait()
    client.aio.files.get.side_effect = pending_poll
    task = asyncio.create_task(_upload_large_file(source, "video/mp4"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert receipt(source)["file_name"] == uploaded.name
    client.aio.files.get.side_effect = None
    assert await _upload_large_file(source, "video/mp4") == uploaded.uri
    assert client.aio.files.upload.await_count == 1


async def test_get_call_cannot_overrun_its_deadline(upload_case):
    _, client, _ = upload_case
    canceled = asyncio.Event()
    async def pending(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            canceled.set()
    client.aio.files.get.side_effect = pending
    with pytest.raises(TimeoutError):
        await video_file._wait_for_active(client, "files/one", timeout=0.02)
    assert canceled.is_set() and client.aio.files.get.await_count == 1


@pytest.mark.parametrize("damage", ["symlink", "fifo"])
async def test_source_nonregular_rejected_before_upload(upload_case, damage):
    source, client, _ = upload_case
    hostile = source.with_name("hostile.mp4")
    if damage == "symlink":
        hostile.symlink_to(source)
    else:
        os.mkfifo(hostile)
    with pytest.raises(PermissionError):
        await _upload_large_file(hostile, "video/mp4")
    client.aio.files.upload.assert_not_called()
    assert source.read_bytes() == b"owned media"


@pytest.mark.parametrize("uri", ["https://api.example/files/other", "https://api.example/files/one?key=secret"])
async def test_invalid_uploaded_identity_blocks_duplicate_submission(upload_case, uri):
    source, client, _ = upload_case
    client.aio.files.upload.return_value = types.File(uri=uri, name="files/one", state="ACTIVE")
    with pytest.raises(ValueError, match="resource identity"):
        await _upload_large_file(source, "video/mp4")
    with pytest.raises(RuntimeError, match="refusing duplicate"):
        await _upload_large_file(source, "video/mp4")
    assert client.aio.files.upload.await_count == 1
    assert "secret" not in json.dumps(JobStore().get(receipt(source)["job_id"]))


async def test_actual_sdk_resumable_upload_and_get_use_owned_bytes(upload_case, monkeypatch):
    source, _, _ = upload_case
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.path == "/upload/v1beta/files":
            return httpx.Response(200, json={}, headers={"x-goog-upload-url": "https://fixture.invalid/upload-chunk"})
        if request.url.path == "/upload-chunk":
            return httpx.Response(200, headers={"x-goog-upload-status": "final"}, json={"file": {"name": "files/wire", "uri": "https://fixture.invalid/files/wire", "state": "PROCESSING"}})
        return httpx.Response(200, json={"name": "files/wire", "uri": "https://fixture.invalid/files/wire", "state": "ACTIVE"})
    transport = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    client = genai.Client(api_key="fixture-key", http_options=types.HttpOptions(httpx_async_client=transport))
    monkeypatch.setattr(video_upload.GeminiClient, "get", lambda: client)
    try:
        assert await _upload_large_file(source, "video/mp4") == "https://fixture.invalid/files/wire"
    finally:
        await client.aio.aclose()
    assert [request.method for request in requests] == ["POST", "POST", "GET"]
    assert json.loads(requests[0].content)["file"]["mime_type"] == "video/mp4"
    assert requests[1].content == source.read_bytes() == b"owned media"
    assert receipt(source)["upload_attempts"] == receipt(source)["poll_attempts"] == 1


async def test_upload_returning_failed_retains_identity_and_stops_before_poll(upload_case):
    source, client, uploaded = upload_case
    uploaded.state = types.FileState.FAILED
    with pytest.raises(video_upload.FileUnavailable):
        await _upload_large_file(source, "video/mp4")
    assert receipt(source)["provider_state"] == "FAILED"
    client.aio.files.get.assert_not_called()
    assert client.aio.files.upload.await_count == 1


@pytest.mark.parametrize("damage", ["mismatched_name", "mismatched_uri", "missing_name", "missing_uri"])
async def test_actual_sdk_retained_get_identity_blocks_duplicate_launch(upload_case, monkeypatch, damage):
    source, _, _ = upload_case
    requests = []
    identity = {"name": "files/retained", "uri": "https://fixture.invalid/files/retained"}
    broken = dict(identity, state="ACTIVE")
    if damage == "mismatched_name":
        broken.update(name="files/other", uri="https://fixture.invalid/files/other")
    elif damage == "mismatched_uri":
        broken["uri"] = "https://other.invalid/files/retained"
    else:
        broken.pop(damage.removeprefix("missing_"))
    def respond(request):
        requests.append(request)
        if request.url.path == "/upload/v1beta/files":
            return httpx.Response(200, json={}, headers={"x-goog-upload-url": "https://fixture.invalid/upload-chunk"})
        if request.url.path == "/upload-chunk":
            return httpx.Response(200, headers={"x-goog-upload-status": "final"},
                                  json={"file": dict(identity, state="PROCESSING")})
        return httpx.Response(200, json=dict(identity, state="ACTIVE") if len(requests) == 3 else broken)
    transport = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    client = genai.Client(api_key="fixture-key", http_options=types.HttpOptions(httpx_async_client=transport))
    monkeypatch.setattr(video_upload.GeminiClient, "get", lambda: client)
    try:
        assert await _upload_large_file(source, "video/mp4") == identity["uri"]
        first_id = receipt(source)["job_id"]
        for _ in range(2):
            with pytest.raises(ValueError, match="identity"):
                await _upload_large_file(source, "video/mp4")
    finally:
        await client.aio.aclose()
    retained = receipt(source)
    assert [request.method for request in requests] == ["POST", "POST", "GET", "GET", "GET"]
    assert requests[1].content == source.read_bytes() == b"owned media"
    assert retained["job_id"] == first_id and retained["status"] == "unknown" and retained["owner"] is None
    assert retained["file_name"] == identity["name"] and retained["file_uri"] == identity["uri"]
    assert retained["upload_attempts"] == 1 and retained["poll_attempts"] == 3
    assert retained["attestation"]["request_integrity"] == retained["attestation"]["result_integrity"] == "verified"
