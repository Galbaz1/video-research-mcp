"""Checked media body boundaries and zero-media metadata transport."""

from contextlib import asynccontextmanager
import hashlib
from unittest.mock import AsyncMock

import pytest

from video_research_mcp import media_fetch
from video_research_mcp.url_policy import UrlPolicyError


class Response:
    def __init__(self, chunks, headers=None):
        self.headers = headers or {}
        self.url = 'https://example.org/final'
        self.chunks = chunks
        self.iterations = 0

    async def aiter_bytes(self):
        self.iterations += 1
        for chunk in self.chunks:
            yield chunk


def install(monkeypatch, response):
    calls = []

    @asynccontextmanager
    async def checked(url, method='GET'):
        calls.append((url, method))
        yield response

    monkeypatch.setattr(media_fetch, 'checked_response', checked)
    return calls


async def test_head_never_consumes_media_body(monkeypatch):
    response = Response([b'video'], {'content-type': 'video/mp4', 'content-length': '5'})
    calls = install(monkeypatch, response)
    result = await media_fetch.head_resource('https://example.org/video')
    assert result['content_length'] == 5
    assert response.iterations == 0
    assert calls == [('https://example.org/video', 'HEAD')]


async def test_loom_metadata_rejects_changed_get_headers_before_body(monkeypatch, tmp_path):
    existing = set(tmp_path.iterdir())
    response = Response([b'video'], {'content-type': 'video/mp4'})
    install(monkeypatch, response)
    with pytest.raises(UrlPolicyError, match='metadata retrieval'):
        await media_fetch.fetch_resource('https://example.org/share', tmp_path, max_bytes=20,
                                         allowed_content_types=('text/html',))
    assert response.iterations == 0
    assert set(tmp_path.iterdir()) == existing


async def test_stream_digest_and_unique_owned_output(monkeypatch, tmp_path):
    response = Response([b'abc', b'def'], {'content-type': 'video/mp4'})
    install(monkeypatch, response)
    first = await media_fetch.fetch_resource('https://example.org/video', tmp_path, max_bytes=6)
    second = await media_fetch.fetch_resource('https://example.org/video', tmp_path, max_bytes=6)
    assert first['sha256'] == hashlib.sha256(b'abcdef').hexdigest()
    assert first['bytes'] == 6
    assert first['path'].read_bytes() == b'abcdef'
    assert first['path'] != second['path']
    assert first['path'].stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('headers', [{}, {'content-length': '7'}])
async def test_size_overflow_cleans_only_owned_file(monkeypatch, tmp_path, headers):
    sibling = tmp_path / 'original'
    sibling.write_bytes(b'keep')
    existing = set(tmp_path.iterdir())
    response = Response([b'abc', b'defg'], headers)
    install(monkeypatch, response)
    with pytest.raises(UrlPolicyError, match='size limit'):
        await media_fetch.fetch_resource('https://example.org/video', tmp_path, max_bytes=6)
    assert set(tmp_path.iterdir()) == existing


async def test_midstream_cancel_removes_partial(monkeypatch, tmp_path):
    import asyncio

    existing = set(tmp_path.iterdir())
    response = Response([])
    async def chunks():
        yield b'first'
        raise asyncio.CancelledError
    response.aiter_bytes = chunks
    install(monkeypatch, response)
    with pytest.raises(asyncio.CancelledError):
        await media_fetch.fetch_resource('https://example.org/video', tmp_path, max_bytes=10)
    assert set(tmp_path.iterdir()) == existing


async def test_head_uses_shared_security_boundary(monkeypatch):
    from video_research_mcp import url_policy

    validate = AsyncMock(side_effect=UrlPolicyError('blocked address'))
    monkeypatch.setattr(url_policy, 'validate_url', validate)
    with pytest.raises(UrlPolicyError, match='blocked address'):
        await media_fetch.head_resource('https://private.example/video')
    validate.assert_awaited_once()
