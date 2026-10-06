"""Tests for URL policy validation and safe download."""

from __future__ import annotations

import gzip
import socket
import zlib
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import httpx
import pytest

from video_research_mcp.url_policy import (
    UrlPolicyError,
    _verify_peer_ip,
    download_checked,
    checked_response,
    validate_url,
)

_DNS_MOCK_TARGET = "video_research_mcp.url_policy._resolve_dns"


def _mock_getaddrinfo(ip: str):
    """Return a mock getaddrinfo result resolving to the given IP."""
    return [(2, 1, 6, "", (ip, 0))]


class _FakeNetworkStream:
    """Mock network stream that reports a peer address."""

    def __init__(self, peer_ip: str, port: int = 443):
        self._peer = (peer_ip, port)

    def get_extra_info(self, info: str, default=None):
        if info == "server_addr":
            return self._peer
        return default


class _AsyncIterBytes:
    """Async iterator that yields chunks of bytes."""

    def __init__(self, chunks: list[bytes]):
        self._chunks = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration


class _FakeResponse:
    """Minimal httpx response mock with async streaming."""

    def __init__(
        self,
        chunks: list[bytes],
        *,
        peer_ip: str | None = "93.184.216.34",
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ):
        self._chunks = chunks
        self.url: httpx.URL | None = None  # Set by _FakeClient.stream or test
        self.extensions: dict = {}
        self.status_code = status_code
        self.headers = headers or {}
        if peer_ip:
            self.extensions["network_stream"] = _FakeNetworkStream(peer_ip)

    def raise_for_status(self):
        pass

    def aiter_bytes(self):
        return _AsyncIterBytes(self._chunks)


class _FakeStreamCtx:
    """Async context manager wrapping a FakeResponse."""

    def __init__(self, resp: _FakeResponse):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *args):
        pass


class _FakeClient:
    """Minimal httpx.AsyncClient mock."""

    def __init__(self, resp: _FakeResponse | list[_FakeResponse]):
        self._responses = resp if isinstance(resp, list) else [resp]
        self.called_urls: list[str] = []

    def stream(self, method, url):
        self.called_urls.append(url)
        idx = len(self.called_urls) - 1
        resp = self._responses[idx] if idx < len(self._responses) else self._responses[-1]
        if resp.url is None:
            resp.url = httpx.URL(url)
        return _FakeStreamCtx(resp)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class TestValidateUrl:
    @patch(_DNS_MOCK_TARGET, new_callable=AsyncMock, return_value=[])
    async def test_empty_dns_result_is_not_a_public_address(self, _mock_dns):
        with pytest.raises(UrlPolicyError, match="no addresses"):
            await validate_url("https://example.org/file")

    async def test_file_uri_cannot_enter_network_adapter(self):
        with pytest.raises(UrlPolicyError, match="Only HTTPS"):
            await validate_url("file:///etc/passwd")

    """Tests for validate_url()."""

    async def test_rejects_http(self):
        """HTTP scheme is blocked — only HTTPS allowed."""
        with pytest.raises(UrlPolicyError, match="Only HTTPS"):
            await validate_url("http://example.com/doc.pdf")

    async def test_rejects_ftp(self):
        """FTP scheme is blocked."""
        with pytest.raises(UrlPolicyError, match="Only HTTPS"):
            await validate_url("ftp://example.com/doc.pdf")

    @patch(_DNS_MOCK_TARGET, new_callable=AsyncMock, return_value=_mock_getaddrinfo("93.184.216.34"))
    async def test_accepts_https(self, _mock_dns):
        """HTTPS with a public IP passes."""
        await validate_url("https://example.com/doc.pdf")

    async def test_rejects_credentials(self):
        """URLs with embedded user:pass are blocked."""
        with pytest.raises(UrlPolicyError, match="embedded credentials"):
            await validate_url("https://user:pass@example.com/doc.pdf")

    async def test_rejects_username_only(self):
        """URLs with embedded username (no password) are blocked."""
        with pytest.raises(UrlPolicyError, match="embedded credentials"):
            await validate_url("https://user@example.com/doc.pdf")

    async def test_rejects_no_hostname(self):
        """URLs without a hostname are blocked."""
        with pytest.raises(UrlPolicyError, match="no hostname"):
            await validate_url("https:///path/to/doc.pdf")

    @patch(_DNS_MOCK_TARGET, new_callable=AsyncMock, return_value=_mock_getaddrinfo("192.168.1.1"))
    async def test_rejects_private_ip(self, _mock_dns):
        """Private IPs (192.168.x.x) are blocked."""
        with pytest.raises(UrlPolicyError, match="blocked IP range"):
            await validate_url("https://internal.corp/doc.pdf")

    @patch(_DNS_MOCK_TARGET, new_callable=AsyncMock, return_value=_mock_getaddrinfo("10.0.0.1"))
    async def test_rejects_private_10_range(self, _mock_dns):
        """Private IPs (10.x.x.x) are blocked."""
        with pytest.raises(UrlPolicyError, match="blocked IP range"):
            await validate_url("https://internal.corp/doc.pdf")

    @patch(_DNS_MOCK_TARGET, new_callable=AsyncMock, return_value=_mock_getaddrinfo("127.0.0.1"))
    async def test_rejects_loopback(self, _mock_dns):
        """Loopback (127.0.0.1) is blocked."""
        with pytest.raises(UrlPolicyError, match="blocked IP range"):
            await validate_url("https://localhost/doc.pdf")

    @patch(_DNS_MOCK_TARGET, new_callable=AsyncMock, return_value=_mock_getaddrinfo("169.254.169.254"))
    async def test_rejects_link_local(self, _mock_dns):
        """Link-local (169.254.x.x, cloud metadata) is blocked."""
        with pytest.raises(UrlPolicyError, match="blocked IP range"):
            await validate_url("https://metadata.google.internal/doc.pdf")

    @patch(_DNS_MOCK_TARGET, new_callable=AsyncMock, side_effect=socket.gaierror("Name resolution failed"))
    async def test_rejects_dns_failure(self, _mock_dns):
        """DNS resolution failure is blocked."""
        with pytest.raises(UrlPolicyError, match="DNS resolution failed"):
            await validate_url("https://nonexistent.example.invalid/doc.pdf")


async def test_research_allowlist_blocks_initial_host_before_dns():
    with patch(_DNS_MOCK_TARGET, new_callable=AsyncMock) as dns:
        with pytest.raises(UrlPolicyError, match="allowlist"):
            async with checked_response("https://blocked.example/file", allowed_hosts={"allowed.example"}):
                pytest.fail("Unpermitted host opened")
        dns.assert_not_called()


async def test_research_allowlist_blocks_redirect_before_dns_and_http():
    response = _FakeResponse([], status_code=302, headers={"location": "https://blocked.example/file"})
    client = _FakeClient(response)
    with patch(_DNS_MOCK_TARGET, new_callable=AsyncMock, return_value=_mock_getaddrinfo("93.184.216.34")) as dns, patch("httpx.AsyncClient", return_value=client):
        with pytest.raises(UrlPolicyError, match="allowlist"):
            async with checked_response("https://allowed.example/file", allowed_hosts={"allowed.example"}):
                pytest.fail("Unpermitted redirect opened")
    assert client.called_urls == ["https://allowed.example/file"] and dns.call_count == 1


class TestVerifyPeerIp:
    """Tests for _verify_peer_ip() DNS rebinding guard."""

    def test_blocks_private_peer_ip(self):
        """GIVEN a response connected to a private IP,
        WHEN _verify_peer_ip is called,
        THEN it raises UrlPolicyError with rebinding message.
        """
        resp = MagicMock()
        resp.extensions = {"network_stream": _FakeNetworkStream("10.0.0.1")}
        with pytest.raises(UrlPolicyError, match="DNS rebinding detected"):
            _verify_peer_ip(resp)

    def test_blocks_loopback_peer_ip(self):
        """Loopback peer IP triggers rebinding detection."""
        resp = MagicMock()
        resp.extensions = {"network_stream": _FakeNetworkStream("127.0.0.1")}
        with pytest.raises(UrlPolicyError, match="DNS rebinding detected"):
            _verify_peer_ip(resp)

    def test_blocks_link_local_peer_ip(self):
        """Link-local peer IP (cloud metadata) triggers rebinding detection."""
        resp = MagicMock()
        resp.extensions = {"network_stream": _FakeNetworkStream("169.254.169.254")}
        with pytest.raises(UrlPolicyError, match="DNS rebinding detected"):
            _verify_peer_ip(resp)

    def test_passes_public_peer_ip(self):
        """Public peer IP passes verification."""
        resp = MagicMock()
        resp.extensions = {"network_stream": _FakeNetworkStream("93.184.216.34")}
        _verify_peer_ip(resp)  # Should not raise

    def test_rejects_without_network_stream(self):
        """An adapter cannot bypass peer verification by omitting transport metadata."""
        resp = MagicMock()
        resp.extensions = {}
        with pytest.raises(UrlPolicyError, match="Cannot verify connected peer"):
            _verify_peer_ip(resp)

    def test_rejects_without_server_address(self):
        """An unknown actual peer cannot establish a public connection."""
        stream = MagicMock()
        stream.get_extra_info.return_value = None
        resp = MagicMock()
        resp.extensions = {"network_stream": stream}
        with pytest.raises(UrlPolicyError, match="Cannot verify connected peer"):
            _verify_peer_ip(resp)

    def test_installed_httpcore_stream_blocks_private_peer(self):
        """Use the installed backend's actual metadata contract without network I/O."""
        from httpcore._backends.anyio import AnyIOStream
        import anyio

        socket_stream = MagicMock()
        def extra(attribute, default=None):
            if attribute == anyio.abc.SocketAttribute.remote_address:
                return ("127.0.0.1", 443)
            return default
        socket_stream.extra.side_effect = extra
        resp = MagicMock()
        resp.extensions = {"network_stream": AnyIOStream(socket_stream)}
        with pytest.raises(UrlPolicyError, match="DNS rebinding detected"):
            _verify_peer_ip(resp)


class TestDownloadChecked:
    """Tests for download_checked()."""

    async def test_enforces_size_limit(self, tmp_path: Path):
        """Downloads exceeding max_bytes raise UrlPolicyError."""
        large_chunk = b"x" * 1000
        resp = _FakeResponse([large_chunk, large_chunk])
        client = _FakeClient(resp)

        with (
            patch("video_research_mcp.url_policy.validate_url", new_callable=AsyncMock),
            patch("video_research_mcp.url_policy.httpx.AsyncClient", return_value=client),
        ):
            with pytest.raises(UrlPolicyError, match="exceeds size limit"):
                await download_checked(
                    "https://example.com/huge.pdf", tmp_path, max_bytes=500
                )

    async def test_uses_manual_redirect_handling(self, tmp_path: Path):
        """Client is created with follow_redirects=False for pre-hop validation."""
        resp = _FakeResponse([b"content"])
        client = _FakeClient(resp)
        mock_cls = MagicMock(return_value=client)

        with (
            patch("video_research_mcp.url_policy.validate_url", new_callable=AsyncMock),
            patch("video_research_mcp.url_policy.httpx.AsyncClient", mock_cls),
        ):
            await download_checked(
                "https://example.com/doc.pdf", tmp_path, max_bytes=10_000
            )
            mock_cls.assert_called_once_with(follow_redirects=False, timeout=60, trust_env=False, transport=ANY, headers={"Accept-Encoding": "identity"})

    async def test_redirect_validates_final_url(self, tmp_path: Path):
        """GIVEN a URL that redirects to a different host,
        WHEN download_checked runs,
        THEN it calls validate_url on the final redirected URL.
        """
        first = _FakeResponse([], status_code=302, headers={"location": "https://cdn.example.com/doc.pdf"})
        final = _FakeResponse([b"content"], status_code=200)
        client = _FakeClient([first, final])

        validate_calls = []
        original_validate = AsyncMock(side_effect=lambda url: validate_calls.append(url))

        with (
            patch("video_research_mcp.url_policy.validate_url", original_validate),
            patch("video_research_mcp.url_policy.httpx.AsyncClient", return_value=client),
        ):
            await download_checked(
                "https://example.com/doc.pdf", tmp_path, max_bytes=10_000
            )

        # Pre-flight validation + per-hop redirect validation
        assert validate_calls == [
            "https://example.com/doc.pdf",
            "https://cdn.example.com/doc.pdf",
        ]
        assert client.called_urls == [
            "https://example.com/doc.pdf",
            "https://cdn.example.com/doc.pdf",
        ]

    async def test_blocks_redirect_before_following_blocked_target(self, tmp_path: Path):
        """Redirect target is validated before a second request is sent."""
        first = _FakeResponse([], status_code=302, headers={"location": "https://blocked.internal/doc.pdf"})
        client = _FakeClient([first])

        async def _validate(url: str):
            if "blocked.internal" in url:
                raise UrlPolicyError("blocked target")

        with (
            patch("video_research_mcp.url_policy.validate_url", side_effect=_validate),
            patch("video_research_mcp.url_policy.httpx.AsyncClient", return_value=client),
        ):
            with pytest.raises(UrlPolicyError, match="blocked target"):
                await download_checked(
                    "https://example.com/doc.pdf", tmp_path, max_bytes=10_000
                )

        # No request should be made to blocked.internal.
        assert client.called_urls == ["https://example.com/doc.pdf"]

    async def test_writes_file(self, tmp_path: Path):
        """Happy path: file is written to tmp_dir."""
        content = b"PDF content here"
        resp = _FakeResponse([content])
        client = _FakeClient(resp)

        with (
            patch("video_research_mcp.url_policy.validate_url", new_callable=AsyncMock),
            patch("video_research_mcp.url_policy.httpx.AsyncClient", return_value=client),
        ):
            result = await download_checked(
                "https://example.com/report.pdf", tmp_path, max_bytes=10_000
            )

        assert result == tmp_path / "report.pdf"
        assert result.read_bytes() == content

    async def test_fallback_filename(self, tmp_path: Path):
        """URLs without a file extension use document.pdf as filename."""
        resp = _FakeResponse([b"data"])
        client = _FakeClient(resp)

        with (
            patch("video_research_mcp.url_policy.validate_url", new_callable=AsyncMock),
            patch("video_research_mcp.url_policy.httpx.AsyncClient", return_value=client),
        ):
            result = await download_checked(
                "https://example.com/download", tmp_path, max_bytes=10_000
            )

        assert result.name == "document.pdf"

    async def test_calls_verify_peer_ip(self, tmp_path: Path):
        """download_checked calls _verify_peer_ip on the response."""
        resp = _FakeResponse([b"data"])
        client = _FakeClient(resp)

        with (
            patch("video_research_mcp.url_policy.validate_url", new_callable=AsyncMock),
            patch("video_research_mcp.url_policy.httpx.AsyncClient", return_value=client),
            patch("video_research_mcp.url_policy._verify_peer_ip") as mock_verify,
        ):
            await download_checked(
                "https://example.com/doc.pdf", tmp_path, max_bytes=10_000
            )
            mock_verify.assert_called_once()

    async def test_rebinding_aborts_before_write(self, tmp_path: Path):
        """GIVEN a DNS rebinding attack (peer resolves to private IP),
        WHEN download_checked runs,
        THEN it raises before writing any data to disk.
        """
        resp = _FakeResponse([b"secret data"], peer_ip="10.0.0.1")
        client = _FakeClient(resp)

        with (
            patch("video_research_mcp.url_policy.validate_url", new_callable=AsyncMock),
            patch("video_research_mcp.url_policy.httpx.AsyncClient", return_value=client),
        ):
            with pytest.raises(UrlPolicyError, match="DNS rebinding detected"):
                await download_checked(
                    "https://evil.com/doc.pdf", tmp_path, max_bytes=10_000
                )

        # Verify no document file was written
        assert not (tmp_path / "doc.pdf").exists()


@pytest.mark.parametrize('ip', ['100.64.0.1', '0.0.0.0', '::', '192.0.0.8'])
async def test_non_global_addresses_never_establish_a_public_fetch(ip):
    with patch(_DNS_MOCK_TARGET, new_callable=AsyncMock, return_value=_mock_getaddrinfo(ip)):
        with pytest.raises(UrlPolicyError, match='blocked IP range'):
            await validate_url('https://nonpublic.example/video')
    with pytest.raises(UrlPolicyError, match='blocked range'):
        _verify_peer_ip(_FakeResponse([], peer_ip=ip))


async def test_rejected_download_does_not_delete_existing_sibling(tmp_path):
    sentinel = tmp_path / 'original.pdf'
    sentinel.write_bytes(b'keep original')
    with pytest.raises(UrlPolicyError):
        await download_checked('http://example.org/original.pdf', tmp_path, max_bytes=10)
    assert sentinel.read_bytes() == b'keep original'


async def test_checked_download_never_overwrites_existing_file(tmp_path):
    sentinel = tmp_path / 'original.pdf'
    sentinel.write_bytes(b'keep original')
    with (
        patch('video_research_mcp.url_policy.validate_url', new_callable=AsyncMock),
        patch('video_research_mcp.url_policy.httpx.AsyncClient', return_value=_FakeClient(_FakeResponse([b'new']))),
    ):
        with pytest.raises(FileExistsError):
            await download_checked('https://example.org/original.pdf', tmp_path, max_bytes=10)
    assert sentinel.read_bytes() == b'keep original'


class _ObservedHTTPXStream(httpx.AsyncByteStream):
    """Observe actual HTTPX body consumption without a network or large payload."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.consumed_bytes = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.consumed_bytes += len(chunk)
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.fixture
def actual_httpx_responses(monkeypatch):
    """Keep the real AsyncClient/Response while replacing only DNS and transport."""
    monkeypatch.setattr(_DNS_MOCK_TARGET, AsyncMock(return_value=_mock_getaddrinfo("93.184.216.34")))

    def install(responses):
        remaining = iter(responses)
        requests = []

        def handle(request):
            requests.append(request)
            response = next(remaining)
            response.extensions["network_stream"] = _FakeNetworkStream("93.184.216.34")
            return response

        monkeypatch.setattr("video_research_mcp.url_policy._PinnedTransport", lambda addresses: httpx.MockTransport(handle))
        return requests

    return install


@pytest.mark.parametrize("encodings", [
    ["gzip"], ["deflate"], ["br"], ["GZip"], ["identity, gzip"],
    ["gzip, identity"], ["identity", "gzip"], [""],
], ids=["gzip", "deflate", "br", "case", "stacked", "reverse", "duplicate", "empty"])
async def test_encoded_response_is_refused_before_decoder_stream_or_file(
    tmp_path, actual_httpx_responses, encodings,
):
    """GIVEN ignored identity negotiation, THEN refuse before decoding or creating output."""
    body = gzip.compress(b"small fixture") if encodings[0].lower() == "gzip" else zlib.compress(b"small fixture")
    stream = _ObservedHTTPXStream([body])
    actual_httpx_responses([httpx.Response(200, headers=[("content-encoding", value) for value in encodings], stream=stream)])
    error = None
    with patch.object(httpx.Response, "_get_content_decoder", autospec=True, side_effect=httpx.Response._get_content_decoder) as decoder:
        try:
            await download_checked("https://example.org/document.pdf", tmp_path, max_bytes=64)
        except UrlPolicyError as exc:
            error = exc
    assert (decoder.call_count, stream.consumed_bytes, (tmp_path / "document.pdf").exists()) == (0, 0, False)
    assert isinstance(error, UrlPolicyError) and "Content-Encoding" in str(error)
    assert stream.closed


@pytest.mark.parametrize("encoding", [None, "identity", "Identity"])
@pytest.mark.parametrize("max_bytes", [4, 3])
async def test_actual_identity_stream_preserves_success_and_size_cleanup(
    tmp_path, actual_httpx_responses, encoding, max_bytes,
):
    """GIVEN an unencoded stream, THEN retain exact success or reject/clean over-limit output."""
    stream = _ObservedHTTPXStream([b"ab", b"cd"])
    headers = {} if encoding is None else {"content-encoding": encoding}
    requests = actual_httpx_responses([httpx.Response(200, headers=headers, stream=stream)])
    if max_bytes == 4:
        result = await download_checked("https://example.org/document.pdf", tmp_path, max_bytes=max_bytes)
        assert result.read_bytes() == b"abcd"
    else:
        with pytest.raises(UrlPolicyError, match="exceeds size limit"):
            await download_checked("https://example.org/document.pdf", tmp_path, max_bytes=max_bytes)
        assert not (tmp_path / "document.pdf").exists()
    assert requests[0].headers["accept-encoding"] == "identity"
    assert stream.consumed_bytes == 4 and stream.closed


async def test_identity_header_persists_across_actual_manual_redirects(tmp_path, actual_httpx_responses):
    """GIVEN two manual redirects, THEN every real HTTPX request asks for identity."""
    streams = [_ObservedHTTPXStream([]), _ObservedHTTPXStream([]), _ObservedHTTPXStream([b"data"])]
    responses = [
        httpx.Response(302, headers={"location": "https://cdn.example.org/step"}, stream=streams[0]),
        httpx.Response(307, headers={"location": "/document.pdf"}, stream=streams[1]),
        httpx.Response(200, stream=streams[2]),
    ]
    requests = actual_httpx_responses(responses)
    result = await download_checked("https://example.org/start", tmp_path, max_bytes=4)
    assert result.read_bytes() == b"data"
    assert [str(request.url) for request in requests] == [
        "https://example.org/start", "https://cdn.example.org/step", "https://cdn.example.org/document.pdf",
    ]
    assert [request.headers["accept-encoding"] for request in requests] == ["identity"] * 3
    assert all(stream.closed for stream in streams)


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br"])
async def test_head_encoded_metadata_does_not_consume_a_body(actual_httpx_responses, encoding):
    """GIVEN HEAD metadata for an encoded resource, THEN yield metadata without reading/decoding."""
    stream = _ObservedHTTPXStream([b"never consumed"])
    requests = actual_httpx_responses([httpx.Response(200, headers={"content-encoding": encoding}, stream=stream)])
    with patch.object(httpx.Response, "_get_content_decoder", autospec=True, side_effect=httpx.Response._get_content_decoder) as decoder:
        async with checked_response("https://example.org/document.pdf", method="HEAD") as response:
            assert response.headers["content-encoding"] == encoding
    assert requests[0].method == "HEAD" and requests[0].headers["accept-encoding"] == "identity"
    assert decoder.call_count == stream.consumed_bytes == 0 and stream.closed


@pytest.mark.parametrize("suffix", [
    "#opaque-fragment-canary",
    "?download=opaque-query-canary#opaque-fragment-canary",
], ids=["opaque-fragment", "query-and-fragment"])
async def test_document_fragment_filename_diagnostics_and_source_identity(
    tmp_path, actual_httpx_responses, monkeypatch, caplog, suffix,
):
    """GIVEN URL metadata, THEN prepare a PDF without leaking it into the filename or issues."""
    import hashlib
    import logging
    from types import SimpleNamespace

    from video_research_mcp.tools import research_document_file as documents

    monkeypatch.setattr("video_research_mcp.config._config", None)
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    url = "https://example.org/paper.pdf" + suffix
    payload = b"%PDF-1.7\nsmall fixture\n"
    content_id = hashlib.sha256(payload).hexdigest()
    scratch = tmp_path / "documents"
    scratch.mkdir()
    stream = _ObservedHTTPXStream([payload])
    requests = actual_httpx_responses([httpx.Response(200, stream=stream)])
    monkeypatch.setattr(documents, "view_directory", lambda: scratch)
    monkeypatch.setattr(documents, "get_config", lambda: SimpleNamespace(
        doc_max_download_bytes=1024, research_document_phase_concurrency=1,
    ))
    upload = AsyncMock(return_value="files/prepared-pdf")
    monkeypatch.setattr(documents, "_upload_large_file", upload)
    caplog.set_level(logging.INFO, logger="video_research_mcp.url_policy")
    with patch.object(documents, "download_checked", wraps=download_checked) as download:
        prepared, issues = await documents._prepare_all_documents_with_issues(None, [url])
    download.assert_called_once_with(url, scratch, max_bytes=1024)
    assert str(requests[0].url) == url
    assert stream.closed and not scratch.exists()
    assert issues == [], caplog.text
    assert prepared == [("files/prepared-pdf", content_id, url)]
    upload.assert_awaited_once_with(scratch / "paper.pdf", "application/pdf", content_hash=content_id)
    assert "opaque-fragment-canary" not in caplog.text
    assert "opaque-query-canary" not in caplog.text
