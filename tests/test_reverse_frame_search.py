"""Synthetic captured-point controls; all publication and Lens exchanges are mocked."""

import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket

import pytest

from tests.test_image_ops import png
from tests.test_native_media_results import metadata
from video_research_mcp.config import update_config
from video_research_mcp.models.reverse_search import ReverseFrameRequest
from video_research_mcp import reverse_frame_search as owner
from video_research_mcp.tools.search_provider import reverse_search_frame

URL = "https://files.uguu.se/fixed.png"


@pytest.fixture
def capture(clean_config, monkeypatch, tmp_path):
    """Declare synthetic point metadata with real local bytes in the owned view fence."""
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    monkeypatch.setenv("SERPER_API_KEY", "selected-serper-secret")
    update_config(search_backends=["serper"])
    source = png(tmp_path / "source.mp4", 4, 2)
    folder = tmp_path / "cache/media/views" / ("a" * 32)
    folder.mkdir(parents=True)
    frame = png(folder / "frame.png", 4, 2)
    value = metadata(source)
    value["frames"][0].update(path=str(frame), requested_seconds=0.25, actual_seconds=0.3,
        original_pts=3072, time_base="1/10240", selection_method="first_decoded_at_or_after",
        delta_seconds=0.05)
    return value


def request(capture, **changes):
    return ReverseFrameRequest(capture=capture, **{"dry_run": False, "authorize_submission": True,
        "authorize_public_upload": True, **changes})


def transport(monkeypatch, capture, *, upload=None, hosted=None, lens=None, fail=None):
    """Replace only external exchanges; keep byte admission, normalization and failure owners real."""
    calls = []
    image = Path(capture["frames"][0]["path"]).read_bytes()
    if upload is not None:
        upload = deepcopy(upload)
        for item in upload.get("files", []):
            if isinstance(item, dict):
                item.setdefault("size", len(image))
    values = [upload if upload is not None else {"success": True, "files": [{"url": URL, "size": len(image)}]},
              image if hosted is None else hosted,
              lens if lens is not None else {"organic": [{"title": "Possible appearance", "link": "https://candidate.example/page",
                  "source": "Candidate publisher", "imageUrl": "https://candidate.example/frame.png",
                  "identity_verified": True, "entity_name": "Injected identity"}]}]

    async def fake(url, **kwargs):
        calls.append((url, kwargs))
        if fail is not None and len(calls) == fail[0]:
            raise fail[1]
        value = values[len(calls) - 1]
        return 200, json.dumps(value).encode() if isinstance(value, dict) else value

    monkeypatch.setattr(owner, "exchange", fake)
    return calls


async def test_capture_upload_readback_lens_retains_lineage_and_pending_identity(capture, monkeypatch):
    """GIVEN an owned point WHEN three mocked exchanges finish THEN bytes and URLs stay bound."""
    calls = transport(monkeypatch, capture)
    result = await reverse_search_frame(request(capture))
    assert result["status"] == "complete" and result["publication"]["status"] == "bytes_verified"
    image = Path(capture["frames"][0]["path"]).read_bytes()
    assert calls[0][0] == "https://uguu.se/upload" and calls[0][1]["method"] == "POST"
    assert image in calls[0][1]["content"] and b'name="files[]"; filename="frame.png"' in calls[0][1]["content"]
    assert "X-API-KEY" not in calls[0][1]["headers"]
    assert calls[1] == (URL, {"content": b"", "headers": {}, "method": "GET"})
    assert calls[2][0] == "https://google.serper.dev/lens"
    assert json.loads(calls[2][1]["content"]) == {"url": URL, "gl": "us", "hl": "en"}
    assert calls[2][1]["headers"]["X-API-KEY"] == "selected-serper-secret"
    assert result["query"]["source_reference"].endswith("#t=0.3")
    assert result["query"]["requested_seconds"] == 0.25 and result["query"]["original_pts"] == 3072
    assert result["query"]["frame_sha256"] == hashlib.sha256(image).hexdigest()
    assert result["query"]["watched_intervals"] == []
    assert result["results"][0]["url"] == "https://candidate.example/page"
    assert result["results"][0]["identity_asserted"] is False
    assert result["identity_asserted"] is False and result["factual_success"] is False
    assert "entity_name" not in json.dumps(result) and result["source_content_role"] == "data"
    assert result["execution"]["physical_requests"] is None and result["execution"]["physical_request_upper_bound"] == 3
    assert result["execution"]["provider_requests_attempted"] == 1 and result["execution"]["direct_requests_reserved"] == 2
    assert result["publication"]["retention_verified"] is False and result["publication"]["deletion_verified"] is False


async def test_dry_run_has_no_public_disclosure_or_external_request(capture, monkeypatch):
    calls = transport(monkeypatch, capture)
    result = await reverse_search_frame(request(capture, dry_run=True, authorize_public_upload=False, authorize_submission=False))
    assert result["status"] == "planned" and not calls
    assert result["publication"]["status"] == "not_attempted" and result["publication"]["url"] is None
    assert result["execution"]["physical_requests"] == 0


@pytest.mark.parametrize("failure", ["key", "disabled", "search_grant", "upload_grant", "source", "frame", "outside_view", "symlink", "byte_cap"])
async def test_missing_authority_or_changed_local_bytes_refuse_before_upload(failure, capture, monkeypatch, tmp_path):
    calls = transport(monkeypatch, capture)
    changes = {}
    if failure == "key":
        monkeypatch.delenv("SERPER_API_KEY")
    elif failure == "disabled":
        update_config(search_backends=[])
    elif failure.endswith("grant"):
        changes["authorize_submission" if failure == "search_grant" else "authorize_public_upload"] = False
    elif failure in {"source", "frame"}:
        (capture["source"] if failure == "source" else capture["frames"][0])["sha256"] = "0" * 64
    elif failure == "outside_view":
        capture["frames"][0]["path"] = capture["source"]["path"]
    elif failure == "symlink":
        link = tmp_path / "link.mp4"
        link.symlink_to(capture["source"]["path"])
        capture["source"]["path"] = str(link)
    else:
        changes["max_response_bytes"] = 1
    result = await reverse_search_frame(request(capture, **changes))
    assert "error" in result and not calls and result["publication"]["status"] == "not_attempted"


@pytest.mark.parametrize("upload", [{"success": False, "files": [{"url": URL}]}, {"files": [{"url": URL}]},
    {"success": True, "files": []}, {"success": True, "files": [{"url": URL}, {"url": URL}]},
    {"success": True, "files": [{"url": "http://files.uguu.se/f.png"}]},
    {"success": True, "files": [{"url": "https://evil.example/f.png"}]},
    {"success": True, "files": [{"url": "https://uguu.se.evil.example/f.png"}]},
    {"success": True, "files": [{"url": "https://files.uguu.se:8443/f.png"}]},
    {"success": True, "files": [{"url": "https://files.uguu.se/selected-serper-secret"}]}])
async def test_unqualified_publication_url_never_reaches_fetch_or_lens(upload, capture, monkeypatch):
    calls = transport(monkeypatch, capture, upload=upload)
    result = await reverse_search_frame(request(capture))
    assert "error" in result and len(calls) == 1 and result["publication"]["status"] == "outcome_unknown"
    assert "selected-serper-secret" not in json.dumps(result)


async def test_hosted_image_mismatch_retains_publication_but_stops_lens(capture, monkeypatch):
    calls = transport(monkeypatch, capture, hosted=b"another image")
    result = await reverse_search_frame(request(capture))
    assert result["error"] == "hosted_query_bytes_differ" and len(calls) == 2
    assert result["publication"]["url"] == URL and result["publication"]["status"] == "url_received"
    assert result["execution"]["provider_requests_attempted"] == 0


@pytest.mark.parametrize("size", [True, "75", 1, 1.5])
async def test_upload_acknowledgement_size_is_exact_before_fetch(size, capture, monkeypatch):
    calls = transport(monkeypatch, capture, upload={"success": True, "files": [{"url": URL, "size": size}]})
    result = await reverse_search_frame(request(capture))
    assert result["error"] == "publication_size_invalid" and len(calls) == 1
    assert result["publication"]["status"] == "outcome_unknown"


async def test_deadline_retains_publication_after_blocked_readback_join(capture, monkeypatch):
    calls = transport(monkeypatch, capture)
    fake, joined = owner.exchange, asyncio.Event()

    async def blocked(url, **kwargs):
        if url != URL:
            return await fake(url, **kwargs)
        try:
            await asyncio.Event().wait()
        finally:
            joined.set()

    monkeypatch.setattr(owner, "exchange", blocked)
    result = await reverse_search_frame(request(capture, timeout_seconds=0.05))
    assert joined.is_set() and result["category"] == "NETWORK_ERROR"
    assert len(calls) == 1
    assert result["publication"]["url"] == URL and len(result["execution"]["calls"]) == 2


async def test_changed_account_cannot_promote_old_results(capture, monkeypatch):
    calls = transport(monkeypatch, capture)
    fake = owner.exchange

    async def drift(url, **kwargs):
        result = await fake(url, **kwargs)
        if len(calls) == 3:
            monkeypatch.setenv("SERPER_API_KEY", "another-account")
        return result

    monkeypatch.setattr(owner, "exchange", drift)
    result = await reverse_search_frame(request(capture))
    assert result["category"] == "PERMISSION_DENIED" and "results" not in result
    assert result["publication"]["url"] == URL and len(calls) == 3


@pytest.mark.parametrize("boundary", [1, 2, 3])
async def test_cancellation_keeps_attempt_and_publication_uncertainty(boundary, capture, monkeypatch):
    entered, joined = asyncio.Event(), asyncio.Event()
    calls = transport(monkeypatch, capture)
    fake = owner.exchange

    async def blocked(url, **kwargs):
        if len(calls) + 1 != boundary:
            return await fake(url, **kwargs)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            joined.set()

    monkeypatch.setattr(owner, "exchange", blocked)
    task = asyncio.create_task(reverse_search_frame(request(capture)))
    await entered.wait()
    task.cancel()
    result = await task
    assert joined.is_set() and result["category"] == "CANCELLED"
    assert len(result["execution"]["calls"]) == boundary and result["execution"]["calls"][-1]["status"] == "interrupted_unknown"
    assert result["publication"]["status"] == {1: "outcome_unknown", 2: "url_received", 3: "bytes_verified"}[boundary]


@pytest.mark.parametrize("body", [{}, {"organic": None}, {"organic": [None] * 101}, {"organic": "not rows"}])
async def test_failed_lens_schema_does_not_become_zero_results(body, capture, monkeypatch):
    calls = transport(monkeypatch, capture, lens=body)
    result = await reverse_search_frame(request(capture))
    assert "error" in result and len(calls) == 3 and "results" not in result


async def test_empty_results_and_rejected_rows_have_distinct_denominators(capture, monkeypatch):
    transport(monkeypatch, capture, lens={"organic": []})
    empty = await reverse_search_frame(request(capture))
    assert empty["status"] == "complete" and empty["returned_population"] == 0
    transport(monkeypatch, capture, lens={"organic": [{"link": "http://unsafe.example"}, {"link": "https://candidate.example/page"}]})
    partial = await reverse_search_frame(request(capture))
    assert partial["status"] == "partial" and partial["returned_population"] == 2
    assert len(partial["results"]) == len(partial["rejections"]) == 1


async def test_local_mutation_after_publication_withholds_search_results(capture, monkeypatch):
    calls = transport(monkeypatch, capture)
    fake = owner.exchange

    async def mutate(url, **kwargs):
        result = await fake(url, **kwargs)
        if len(calls) == 3:
            Path(capture["frames"][0]["path"]).write_bytes(b"changed")
        return result

    monkeypatch.setattr(owner, "exchange", mutate)
    result = await reverse_search_frame(request(capture))
    assert "error" in result and "results" not in result and len(calls) == 3
    assert result["publication"]["url"] == URL and result["publication"]["status"] == "bytes_verified"


def test_approximate_or_incomplete_capture_refused(capture):
    bad = deepcopy(capture)
    bad["frames"][0]["approximate"] = True
    with pytest.raises(ValueError, match="precise"):
        request(bad)


async def test_actual_three_exchange_transport_preserves_origins_and_closes(capture, monkeypatch, caplog):
    """GIVEN actual installed HTTPX WHEN only sockets are mocked THEN upload/readback/key stay fenced."""
    from httpcore._backends.auto import AutoBackend
    from tests.test_vision_http import NetworkStream

    image = Path(capture["frames"][0]["path"]).read_bytes()
    bodies = [json.dumps({"success": True, "files": [{"url": URL, "size": len(image)}]}).encode(), image,
              b'{"organic":[{"link":"https://candidate.example/page","title":"Candidate"}]}']
    streams = [NetworkStream(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body) for body in bodies]
    dns, connected = [], []

    async def resolve(host, port, **kwargs):
        dns.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]

    async def connect(self, host, port, **kwargs):
        connected.append((host, port))
        return streams[len(connected) - 1]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(AutoBackend, "connect_tcp", connect)
    caplog.set_level("DEBUG", logger="httpcore.connection")
    result = await reverse_search_frame(request(capture))
    assert result["status"] == "complete"
    assert dns == ["uguu.se", "files.uguu.se", "google.serper.dev"] and len(connected) == 3
    for host, stream in zip(dns, streams, strict=True):
        wire = b"".join(stream.writes)
        assert f"Host: {host}\r\n".encode() in wire and stream.tls[0][0] == host and stream.closed
        assert (b"selected-serper-secret" in wire) == (host == "google.serper.dev")
    assert image in b"".join(streams[0].writes) and "selected-serper-secret" not in caplog.text


async def test_actual_private_readback_dns_stops_before_lens(capture, monkeypatch):
    """GIVEN acknowledged publication WHEN readback DNS is private THEN no image fetch or Lens starts."""
    from httpcore._backends.auto import AutoBackend
    from tests.test_vision_http import NetworkStream

    data = json.dumps({"success": True, "files": [{"url": URL, "size": capture["frames"][0]["bytes"]}]}).encode()
    stream = NetworkStream(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(data)).encode() + b"\r\n\r\n" + data)
    connected = []

    async def resolve(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1" if host == "files.uguu.se" else "8.8.8.8", port))]

    async def connect(self, host, port, **kwargs):
        connected.append((host, port))
        return stream

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(AutoBackend, "connect_tcp", connect)
    result = await reverse_search_frame(request(capture))
    assert "error" in result and len(connected) == 1 and stream.closed
    assert result["publication"]["status"] == "url_received" and result["publication"]["url"] == URL
    assert result["execution"]["provider_requests_attempted"] == 0


@pytest.mark.parametrize("replacement", ["fifo", "geometry"])
async def test_descriptor_admission_race_never_blocks_or_publishes_wrong_geometry(replacement, capture, monkeypatch, tmp_path):
    """GIVEN replacement at the real descriptor open WHEN admission runs THEN no disclosure occurs."""
    calls = transport(monkeypatch, capture)
    frame = Path(capture["frames"][0]["path"])
    changed = png(tmp_path / "changed.png", 8, 2).read_bytes()
    if replacement == "geometry":
        capture["frames"][0].update(sha256=hashlib.sha256(changed).hexdigest(), bytes=len(changed))
    original, observed = os.open, []

    def race(path, flags, *args, **kwargs):
        if Path(path) == frame and not observed:
            observed.append(flags)
            frame.unlink()
            if replacement == "fifo":
                os.mkfifo(frame)
            else:
                frame.write_bytes(changed)
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", race)
    result = await asyncio.wait_for(reverse_search_frame(request(capture)), timeout=1)
    assert "error" in result and not calls and len(observed) == 1
    assert observed[0] & os.O_NONBLOCK
    assert result["publication"]["status"] == "not_attempted"
