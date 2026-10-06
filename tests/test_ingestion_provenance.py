"""Controller-level original commitments, located evidence and joined ingestion state."""

import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import threading
from contextlib import contextmanager
import wave
from unittest.mock import AsyncMock

import httpx
import pytest

from video_research_mcp import ingestion, ingestion_pdf, ingestion_text, url_policy
from video_research_mcp.config import update_config
from video_research_mcp.evidence import validate_evidence_packet
from video_research_mcp.job_store import JobStore
from video_research_mcp.models.ingestion import SourceIngestRequest
from video_research_mcp.tools.ingestion import source_ingest, source_ingest_cancel, source_ingest_read
from video_research_mcp.tools.research_execute import research_execute


@pytest.fixture(autouse=True)
def isolated(clean_config, monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    monkeypatch.setattr(ingestion_pdf, "run_media_process", AsyncMock(
        side_effect=AssertionError("Native execution is not authorized in these controls")))
    monkeypatch.setattr(url_policy, "_resolve_dns", AsyncMock(
        side_effect=AssertionError("Live DNS is not authorized in these controls")))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def original(tmp_path, body=b"Original fact.\n\nSecond fact.\n", source_format="text", **fields):
    path = tmp_path / {"text": "input.txt", "markdown": "input.md", "html": "input.html",
                       "docx": "input.docx", "pdf": "input.pdf", "audio": "input.wav"}[source_format]
    path.write_bytes(body)
    return SourceIngestRequest(source_id="source-17", revision="revision-4", source_format=source_format,
                               file_path=str(path), expected_source_sha256=sha(body), **fields)


def views(tmp_path):
    base = tmp_path / "cache" / "media" / "views"
    return set(base.iterdir()) if base.exists() else set()


def packet(result, claims=None):
    return {"packet_id": "ingested", "sources": [result["source"]],
            "claims": claims or [], "lineage": []}


@pytest.mark.parametrize("source_format,body", [
    ("text", "Original fact.\r\n\r\nSecond café.\n".encode()),
    ("markdown", b"# Original fact.\n\nSecond fact.\n"),
    ("html", b"<html><body><p>Original fact.</p><p>Second fact.</p></body></html>"),
])
async def test_original_bytes_and_located_quotes_remain_independent(tmp_path, source_format, body):
    """GIVEN original markup/UTF8 WHEN ingested THEN exact bytes and locations survive."""
    request = original(tmp_path, body, source_format)
    result = await ingestion.ingest_source(request)
    assert result["status"] == "completed" and not result["indexed"]
    assert result["source"]["id"] == request.source_id
    assert result["source"]["revision"] == request.revision
    assert result["source"]["sha256"] == sha(body)
    assert result["source"]["asset_kind"] == "original"
    assert Path(result["original"]["path"]).read_bytes() == body
    assert Path(request.file_path).read_bytes() == body
    for passage in result["source"]["passages"]:
        location = passage["location"]
        assert passage["quote"] == body.decode()[location["start_char"]:location["end_char"]]
        assert passage["method"]
    passage = result["source"]["passages"][0]
    claims = [{"id": "literal", "text": passage["quote"],
               "support": [{"source_id": request.source_id, "passage_id": passage["id"]}]},
              {"id": "paraphrase", "text": "An inferred conclusion", "support": []}]
    checked = validate_evidence_packet(packet(result, claims), Path(result["source_root"]))
    assert checked["source_errors"] == []
    assert checked["claim_support"] == {"literal": "exact_source_text", "paraphrase": "unknown"}
    assert checked["factual_success"] is False and checked["contract_passed"] is False


async def test_completed_duplicate_reuses_original_and_restart_readback(tmp_path):
    request = original(tmp_path)
    first = await ingestion.ingest_source(request)
    before = views(tmp_path)
    repeated = await ingestion.ingest_source(request)
    assert repeated["deduplicated"] is True and repeated["job_id"] == first["job_id"]
    assert views(tmp_path) == before
    assert JobStore().get(first["job_id"])["attempts"] == 1
    restarted = await source_ingest_read(first["job_id"])
    assert restarted["extraction"] == first["extraction"] and restarted["artifact_verified"] is True
    Path(request.file_path).write_bytes(b"Later unrelated edit")
    retained = await ingestion.read_ingestion(first["job_id"])
    assert retained["source"]["sha256"] == request.expected_source_sha256
    assert Path(retained["original"]["path"]).read_bytes() != Path(request.file_path).read_bytes()


async def test_ingested_document_is_admitted_by_real_supplied_research_route(tmp_path, mock_gemini_client):
    result = await ingestion.ingest_source(original(tmp_path))
    passage = result["source"]["passages"][0]
    supplied = packet(result, [{"id": "claim-original", "text": passage["quote"],
                                "support": [{"source_id": "source-17", "passage_id": passage["id"]}],
                                "editorial_approved": False, "abstained": False, "confidence": None}])
    researched = await research_execute({"topic": "Preserve this original document", "mode": "supplied",
                                         "source_root": result["source_root"], "supplied_packet": supplied})
    assert researched["status"] == "planned" and researched["rejections"] == []
    assert researched["execution"]["provider_calls"] == 0
    retained = json.loads(Path(researched["artifacts"]["packet_path"]).read_text())
    assert retained["sources"][0]["sha256"] == result["source"]["sha256"]
    assert retained["sources"][0]["passages"] == result["source"]["passages"]
    assert retained["claims"] == supplied["claims"]
    assert researched["artifacts"]["packet_validation"]["source_errors"] == []
    mock_gemini_client["get"].assert_not_called()
    mock_gemini_client["generate"].assert_not_called()
    mock_gemini_client["generate_structured"].assert_not_called()


@pytest.mark.parametrize("change", ["bytes", "revision", "source_id"])
async def test_changed_source_commitment_gets_new_ingestion_identity(tmp_path, change):
    request = original(tmp_path)
    first = await ingestion.ingest_source(request)
    values = request.model_dump()
    if change == "bytes":
        body = b"Different original fact."
        Path(request.file_path).write_bytes(body)
        values["expected_source_sha256"] = sha(body)
    else:
        values[change] = "changed-identity"
    second = await ingestion.ingest_source(SourceIngestRequest(**values))
    assert first["job_id"] != second["job_id"]
    assert second["deduplicated"] is False and second["status"] == "completed"
    assert (await ingestion.read_ingestion(first["job_id"]))["original"] == first["original"]


@pytest.mark.parametrize("body", [b"", b" \n\t", b"\xffinvalid UTF8"])
async def test_empty_or_invalid_extraction_is_terminal_and_retry_deduplicates(tmp_path, body):
    request = original(tmp_path, body)
    first = await ingestion.ingest_source(request)
    assert first["status"] == "failed" and first["indexed"] is False
    assert first["original"]["sha256"] == sha(body)
    assert Path(first["original"]["path"]).read_bytes() == body
    before = views(tmp_path)
    second = await ingestion.ingest_source(request)
    assert second["status"] == "failed" and second["deduplicated"] is True
    assert second["job_id"] == first["job_id"] and views(tmp_path) == before
    assert JobStore().get(first["job_id"])["attempts"] == 1


async def test_malformed_docx_preserves_original_without_success_or_indexing(tmp_path):
    body = b"Not a ZIP or an OOXML document"
    result = await ingestion.ingest_source(original(tmp_path, body, "docx"))
    assert result["status"] == "failed" and result["indexed"] is False
    assert Path(result["original"]["path"]).read_bytes() == body
    assert "extraction" not in result and "source" not in result


@pytest.mark.parametrize("target", ["original", "segments", "manifest"])
async def test_corrupted_retained_artifact_cannot_report_completed(tmp_path, target):
    result = await ingestion.ingest_source(original(tmp_path))
    paths = {"original": result["original"]["path"], "manifest": result["manifest"]["path"],
             "segments": str(Path(result["original"]["path"]).parent / "derived" / "segments.json")}
    Path(paths[target]).write_bytes(b"corrupted")
    reread = await ingestion.read_ingestion(result["job_id"])
    assert reread["status"] == "unknown" and reread["recorded_status"] == "completed"
    assert reread["indexed"] is False and "extraction" not in reread


@pytest.mark.parametrize("malformation", ["non_object", "missing_location", "different_revision"])
async def test_malformed_document_observation_is_rejected_without_exception(tmp_path, malformation):
    result = await ingestion.ingest_source(original(tmp_path))
    value = copy.deepcopy(packet(result))
    source = value["sources"][0]
    record = json.loads(source["snapshot"]["text"])
    if malformation == "non_object":
        record = []
    elif malformation == "missing_location":
        source["passages"][0].pop("location")
    else:
        record["revision"] = "wrong revision"
    text = json.dumps(record)
    source["snapshot"] = {"text": text, "sha256": sha(text.encode())}
    checked = validate_evidence_packet(value, Path(result["source_root"]))
    assert checked["source_errors"] and checked["factual_success"] is False


@pytest.mark.parametrize("kind", ["symlink", "fifo", "directory", "outside", "uri"])
async def test_unsafe_source_never_leaves_retained_staging(tmp_path, kind):
    request = original(tmp_path)
    values = request.model_dump()
    unsafe = tmp_path / "unsafe.txt"
    if kind == "symlink":
        unsafe.symlink_to(request.file_path)
    elif kind == "fifo":
        os.mkfifo(unsafe)
    elif kind == "directory":
        unsafe.mkdir()
    elif kind == "outside":
        fence = tmp_path / "fence"
        fence.mkdir()
        update_config(local_file_access_root=str(fence), cache_dir=str(fence / "cache"))
        unsafe = Path(request.file_path)
    else:
        values["file_path"] = "file://" + request.file_path
    if kind != "uri":
        values["file_path"] = str(unsafe)
    with pytest.raises((PermissionError, ValueError, OSError)):
        await ingestion.ingest_source(SourceIngestRequest(**values))
    base = Path(str(tmp_path / ("fence/cache" if kind == "outside" else "cache"))) / "media" / "views"
    assert not base.exists() or list(base.iterdir()) == []
    assert Path(request.file_path).read_bytes() == b"Original fact.\n\nSecond fact.\n"


async def test_expected_source_digest_failure_cleans_only_owned_staging(tmp_path):
    request = original(tmp_path)
    sentinel = tmp_path / "preserve.txt"
    sentinel.write_bytes(b"preserve")
    changed = request.model_copy(update={"expected_source_sha256": "0" * 64})
    with pytest.raises(ValueError, match="SHA256"):
        await ingestion.ingest_source(changed)
    assert views(tmp_path) == set() and sentinel.read_bytes() == b"preserve"


class Peer:
    def get_extra_info(self, name):
        return ("8.8.8.8", 443) if name == "server_addr" else None


@pytest.mark.parametrize("outcome", ["exact", "blocked_redirect", "private_dns"])
async def test_url_ingestion_reuses_dns_peer_and_seed_host_policy(tmp_path, monkeypatch, outcome):
    calls, dns = [], []
    real_client = httpx.AsyncClient
    body = b"Exact downloaded original.\r\n"

    async def resolve(host):
        dns.append(host)
        address = "127.0.0.1" if outcome == "private_dns" else "8.8.8.8"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    async def respond(request):
        calls.append(str(request.url))
        status, headers = (302, {"location": "https://other.example/source"}) if outcome == "blocked_redirect" else (200, {"content-type": "text/plain"})
        return httpx.Response(status, headers=headers, content=body,
                              extensions={"network_stream": Peer()})

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return real_client(**{**kwargs, "transport": httpx.MockTransport(respond)})

    monkeypatch.setattr(url_policy, "_resolve_dns", resolve)
    monkeypatch.setattr(url_policy.httpx, "AsyncClient", client)
    request = SourceIngestRequest(source_id="remote", revision="url-v1", source_format="text",
                                  url="https://public.example/source", expected_source_sha256=sha(body))
    if outcome == "exact":
        result = await ingestion.ingest_source(request)
        assert result["status"] == "completed"
        assert Path(result["original"]["path"]).read_bytes() == body
        assert result["original"]["representation"] == "decoded_http_response_body"
    else:
        with pytest.raises(url_policy.UrlPolicyError):
            await ingestion.ingest_source(request)
        assert views(tmp_path) == set()
    assert dns == ["public.example"]
    assert len(calls) == (0 if outcome == "private_dns" else 1)


async def test_full_pcm_read_retains_interval_and_abstains_from_speech(tmp_path):
    path = tmp_path / "input.wav"
    frames, rate = 8001, 8000
    pcm = b"\x01\x00\xff\xff" * frames
    with wave.open(str(path), "wb") as writer:
        writer.setparams((2, 2, rate, 0, "NONE", "not compressed"))
        writer.writeframes(pcm)
    body = path.read_bytes()
    request = SourceIngestRequest(source_id="audio-original", revision="pcm-v1", source_format="audio",
                                  file_path=str(path), expected_source_sha256=sha(body))
    result = await ingestion.ingest_source(request)
    assert result["status"] == "completed" and result["source"]["modality"] == "audio"
    assert result["source"]["observed_intervals"] == [{"start_ms": 0, "end_ms": 1001}]
    assert result["source"]["passages"] == []
    segment = result["extraction"]["segments"][0]
    observed = json.loads(Path(segment["artifact"]).read_text())
    assert observed["sample_count"] == frames and observed["channels"] == 2
    assert observed["speech_transcription"] == observed["speaker_attribution"] == "unavailable"
    assert validate_evidence_packet(packet(result), Path(result["source_root"]))["source_errors"] == []
    assert path.read_bytes() == body and result["source"]["sha256"] == sha(body)


async def test_truncated_pcm_header_cannot_claim_full_audio_interval(tmp_path):
    path = tmp_path / "input.wav"
    with wave.open(str(path), "wb") as writer:
        writer.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        writer.writeframes(b"\x01\x00" * 8000)
    body = path.read_bytes()[:-2]
    result = await ingestion.ingest_source(original(tmp_path, body, "audio"))
    assert result["status"] == "failed" and "source" not in result
    assert Path(result["original"]["path"]).read_bytes() == body


@pytest.fixture
def controlled_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(ingestion_pdf, "pixel_profile", lambda: {
        "available": False, "limitation": "PDFium unavailable in this mocked Poppler fixture",
    })
    paths = {name: tmp_path / name for name in ("pdftotext", "pdfimages")}
    for name, path in paths.items():
        path.write_bytes(("owned command identity: " + name).encode())
    monkeypatch.setattr(ingestion_pdf.shutil, "which", lambda name: str(paths[name]))
    state = {"calls": [], "started": asyncio.Event(), "release": asyncio.Event(), "joined": False}

    async def command(argv, timeout):
        state["calls"].append(argv)
        assert 0 < timeout <= 120 and Path(argv[-2] if argv[-1] == "-" else argv[-1]).is_file()
        if Path(argv[0]).name == "pdftotext":
            state["started"].set()
            try:
                await state["release"].wait()
            finally:
                state["joined"] = True
            return (b'<html xmlns="http://www.w3.org/1999/xhtml"><page width="100" height="100">'
                    b'<word xMin="1" yMin="2" xMax="20" yMax="10">Original</word></page></html>', b"")
        return b"page num type width height color comp bpc enc interp object ID\n", b""

    monkeypatch.setattr(ingestion_pdf, "run_media_process", command)
    return state, paths


async def test_changed_actual_pdf_parser_bytes_create_new_identity(tmp_path, controlled_pdf):
    state, paths = controlled_pdf
    state["release"].set()
    request = original(tmp_path, b"%PDF-1.7\nowned original fixture", "pdf")
    first = await ingestion.ingest_source(request)
    paths["pdftotext"].write_bytes(b"changed owned executable identity")
    second = await ingestion.ingest_source(request)
    assert first["status"] == second["status"] == "completed"
    assert first["job_id"] != second["job_id"] and first["parser"] != second["parser"]
    assert first["source"]["sha256"] == second["source"]["sha256"]


async def test_concurrent_exact_duplicate_extracts_once(tmp_path, controlled_pdf):
    """GIVEN retained busy extraction WHEN duplicated THEN one owner performs native calls."""
    state, _ = controlled_pdf
    request = original(tmp_path, b"%PDF-1.7\nowned original fixture", "pdf")
    first = asyncio.create_task(ingestion.ingest_source(request))
    try:
        await asyncio.wait_for(state["started"].wait(), 2)
        second = await asyncio.wait_for(ingestion.ingest_source(request), 2)
        assert second["deduplicated"] is True and second["status"] == "running"
        assert len(state["calls"]) == 1
    finally:
        state["release"].set()
        finished = await first
    assert finished["status"] == "completed" and finished["job_id"] == second["job_id"]
    assert len(state["calls"]) == 2 and JobStore().get(finished["job_id"])["attempts"] == 1


async def test_public_cancel_request_prevents_late_success(tmp_path, controlled_pdf):
    state, _ = controlled_pdf
    request = original(tmp_path, b"%PDF-1.7\nowned original fixture", "pdf")
    task = asyncio.create_task(ingestion.ingest_source(request))
    try:
        await asyncio.wait_for(state["started"].wait(), 2)
        row = JobStore().list_active("source_ingestion")[0]
        cancelled = await source_ingest_cancel(row["job_id"])
        assert cancelled["status"] == "cancel_requested" and cancelled["termination_verified"] is False
    finally:
        state["release"].set()
        result = await task
    assert state["joined"] is True and result["status"] == "cancelled"
    assert (await ingestion.read_ingestion(row["job_id"]))["status"] == "cancelled"
    assert Path(request.file_path).read_bytes() == b"%PDF-1.7\nowned original fixture"


async def test_ingestion_cancel_refuses_another_job_kind():
    row = JobStore().create("video_batch", {"source": "owned"}, "revision")
    result = await source_ingest_cancel(row["job_id"])
    assert "error" in result and JobStore().get(row["job_id"])["status"] == "queued"


async def test_direct_cancellation_joins_native_boundary_before_ack(tmp_path, controlled_pdf):
    state, _ = controlled_pdf
    task = asyncio.create_task(ingestion.ingest_source(original(tmp_path, b"%PDF-1.7\nfixture", "pdf")))
    await asyncio.wait_for(state["started"].wait(), 2)
    row = JobStore().list_active("source_ingestion")[0]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state["joined"] is True
    assert (await ingestion.read_ingestion(row["job_id"]))["status"] == "cancelled"
    state["release"].set()
    assert JobStore().get(row["job_id"])["status"] == "cancelled"


async def test_direct_cancellation_joins_cooperative_regular_file_worker(tmp_path, monkeypatch):
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    real_open = ingestion_text._open_regular

    @contextmanager
    def gated(path):
        with real_open(path) as reader:
            class Reader:
                def fileno(self):
                    return reader.fileno()

                def read(self, count):
                    entered.set()
                    assert release.wait(2)
                    return reader.read(count)
            try:
                yield Reader()
            finally:
                exited.set()

    monkeypatch.setattr(ingestion_text, "_open_regular", gated)
    task = asyncio.create_task(ingestion.ingest_source(original(tmp_path)))
    assert await asyncio.to_thread(entered.wait, 2)
    row = JobStore().list_active("source_ingestion")[0]
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done() and not exited.is_set()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert exited.is_set() and (await ingestion.read_ingestion(row["job_id"]))["status"] == "cancelled"


@pytest.mark.parametrize("failure", ["deadline", "empty-error"])
async def test_public_ingestion_failure_retains_actionable_readback(tmp_path, monkeypatch, failure):
    """GIVEN a claimed failure WHEN read or duplicated THEN its diagnostic and originals survive."""
    update_config(media_acquire_timeout_seconds=1)
    joined = asyncio.Event()

    async def controlled_extract(*args):
        try:
            if failure == "deadline":
                await asyncio.sleep(2)
            raise ValueError()
        finally:
            joined.set()

    extraction = AsyncMock(side_effect=controlled_extract)
    monkeypatch.setattr(ingestion, "_extract", extraction)
    request = original(tmp_path)
    result = await source_ingest(request)
    expected = ("Source ingestion exceeded its 1-second deadline; owned work joined"
                if failure == "deadline" else "ValueError during source extraction")
    assert joined.is_set() and result["status"] == "failed" and result["error"] == expected
    row = JobStore().get(result["job_id"])
    assert row["error"] == row["result"]["error"] == expected
    assert row["owner"] is None and row["attestation"]["artifact_integrity"] == "verified"
    assert Path(result["original"]["path"]).read_bytes() == Path(request.file_path).read_bytes()
    restarted = await source_ingest_read(result["job_id"])
    duplicate = await source_ingest(request)
    assert restarted["status"] == duplicate["status"] == "failed"
    assert restarted["error"] == duplicate["error"] == expected
    assert duplicate["job_id"] == result["job_id"] and duplicate["deduplicated"] is True
    assert JobStore().get(result["job_id"])["attempts"] == 1 and extraction.await_count == 1
