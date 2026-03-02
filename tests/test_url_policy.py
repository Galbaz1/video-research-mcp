"""Tests for URL policy validation and safe download."""

from __future__ import annotations

import socket
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from video_research_mcp.url_policy import (
    UrlPolicyError,
    _verify_peer_ip,
    download_checked,
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
        if info == "peername":
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
        peer_ip: str | None = None,
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

    def test_passes_without_network_stream(self):
        """Missing network_stream extension is tolerated (graceful degradation)."""
        resp = MagicMock()
        resp.extensions = {}
        _verify_peer_ip(resp)  # Should not raise

    def test_passes_without_peername(self):
        """Network stream without peername is tolerated."""
        stream = MagicMock()
        stream.get_extra_info.return_value = None
        resp = MagicMock()
        resp.extensions = {"network_stream": stream}
        _verify_peer_ip(resp)  # Should not raise


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
            mock_cls.assert_called_once_with(follow_redirects=False, timeout=60)

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
