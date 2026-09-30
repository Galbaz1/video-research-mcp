"""YouTube acquisition boundaries, byte receipts and optional explicit cookies."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import video_research_mcp.config as cfg_mod
from video_research_mcp.tools import youtube_download as module

TEST_VIDEO_ID = 'dQw4w9WgXcQ'


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')
    monkeypatch.delenv('MEDIA_COOKIES_FILE', raising=False)
    cfg_mod._config = None
    yield
    cfg_mod._config = None


@pytest.fixture
def download_dir(tmp_path, monkeypatch):
    directory = tmp_path / 'downloads'
    directory.mkdir()
    monkeypatch.setattr(module, '_download_dir', lambda: directory)
    monkeypatch.setattr(module.shutil, 'which', lambda _: '/fixture/yt-dlp')
    return directory


def downloader(monkeypatch, *, failure=None, data=b'fixture video'):
    calls = []
    async def run(command, timeout):
        calls.append((command, timeout))
        Path(command[command.index('-o') + 1]).write_bytes(data)
        if failure:
            raise failure
        return b'', b''
    monkeypatch.setattr(module, 'run_media_process', run)
    return calls


@pytest.mark.parametrize('video_id', ['../outside', 'file:///etc/passwd', 'https://example.org', '--exec=bad'])
async def test_invalid_id_rejected_before_filesystem_or_process(video_id, tmp_path, monkeypatch):
    spawn = AsyncMock()
    monkeypatch.setattr(module, 'run_media_process', spawn)
    target = tmp_path / 'not-created'
    with pytest.raises(ValueError, match='eleven-character'):
        await module.download_youtube_video(video_id, target_dir=target)
    assert not target.exists()
    spawn.assert_not_called()


async def test_success_retains_hash_and_exact_canonical_command(download_dir, monkeypatch):
    calls = downloader(monkeypatch)
    output = await module.download_youtube_video(TEST_VIDEO_ID)
    assert output == download_dir / f'{TEST_VIDEO_ID}.mp4'
    receipt = json.loads(output.with_suffix('.receipt.json').read_text())
    assert receipt == {'version': 1, 'video_id': TEST_VIDEO_ID,
                       'bytes': len(b'fixture video'), 'sha256': hashlib.sha256(b'fixture video').hexdigest()}
    command, timeout = calls[0]
    assert command[-1] == f'https://www.youtube.com/watch?v={TEST_VIDEO_ID}'
    assert timeout == 120
    assert '--ignore-config' in command and '--no-cache-dir' in command
    formats = command[command.index('-f') + 1].split('/')
    assert all('[height<=720]' in f and '[width<=1280]' in f for f in formats)
    assert '--max-filesize' in command
    assert '--cookies-from-browser' not in command
    assert not list(download_dir.glob('.youtube-*'))


async def test_restart_reuses_only_verified_exact_bytes(download_dir, monkeypatch):
    calls = downloader(monkeypatch)
    output = await module.download_youtube_video(TEST_VIDEO_ID)
    module._LOCKS.clear()
    assert await module.download_youtube_video(TEST_VIDEO_ID) == output
    assert len(calls) == 1
    output.write_bytes(b'changed')
    with pytest.raises(ValueError, match='bytes changed'):
        await module.download_youtube_video(TEST_VIDEO_ID)
    assert len(calls) == 1


async def test_nonempty_legacy_cache_remains_unknown(download_dir, monkeypatch):
    original = download_dir / f'{TEST_VIDEO_ID}.mp4'
    original.write_bytes(b'legacy')
    calls = downloader(monkeypatch)
    with pytest.raises(ValueError, match='provenance is unknown'):
        await module.download_youtube_video(TEST_VIDEO_ID)
    assert original.read_bytes() == b'legacy'
    assert calls == []


async def test_empty_legacy_cache_is_replaced(download_dir, monkeypatch):
    (download_dir / f'{TEST_VIDEO_ID}.mp4').write_bytes(b'')
    downloader(monkeypatch)
    assert (await module.download_youtube_video(TEST_VIDEO_ID)).read_bytes() == b'fixture video'


async def test_oversized_cache_never_reaches_process(download_dir, monkeypatch):
    monkeypatch.setenv('MEDIA_MAX_INPUT_BYTES', '9')
    (download_dir / f'{TEST_VIDEO_ID}.mp4').write_bytes(b'0123456789')
    calls = downloader(monkeypatch)
    with pytest.raises(ValueError, match='MEDIA_MAX_INPUT_BYTES'):
        await module.download_youtube_video(TEST_VIDEO_ID)
    assert calls == []


async def test_missing_downloader_is_actionable(download_dir, monkeypatch):
    monkeypatch.setattr(module.shutil, 'which', lambda _: None)
    with pytest.raises(RuntimeError, match='yt-dlp not found'):
        await module.download_youtube_video(TEST_VIDEO_ID)


@pytest.mark.parametrize('failure', [RuntimeError('Video unavailable'), TimeoutError(), asyncio.CancelledError()])
async def test_failure_timeout_cancel_cleanup_only_owned_staging(download_dir, monkeypatch, failure):
    sibling = download_dir / 'keep.mp4'
    sibling.write_bytes(b'keep')
    downloader(monkeypatch, failure=failure)
    with pytest.raises((RuntimeError, asyncio.CancelledError)):
        await module.download_youtube_video(TEST_VIDEO_ID)
    assert list(download_dir.iterdir()) == [sibling]


async def test_actual_output_limit_checked_even_if_downloader_ignores_flag(download_dir, monkeypatch):
    monkeypatch.setenv('MEDIA_MAX_INPUT_BYTES', '3')
    downloader(monkeypatch)
    with pytest.raises(ValueError, match='MEDIA_MAX_INPUT_BYTES'):
        await module.download_youtube_video(TEST_VIDEO_ID)
    assert list(download_dir.iterdir()) == []


async def test_explicit_cookie_file_and_unavailable_cookie_errors(download_dir, tmp_path, monkeypatch):
    cookie = tmp_path / 'explicit.cookies'
    cookie.write_text('# Netscape HTTP Cookie File\n')
    monkeypatch.setenv('LOCAL_FILE_ACCESS_ROOT', str(tmp_path))
    monkeypatch.setenv('MEDIA_COOKIES_FILE', str(cookie))
    calls = downloader(monkeypatch)
    await module.download_youtube_video(TEST_VIDEO_ID)
    assert calls[0][0][calls[0][0].index('--cookies') + 1] == str(cookie.resolve())
    cookie.unlink()
    with pytest.raises(ValueError, match='MEDIA_COOKIES_FILE is unavailable'):
        await module.download_youtube_video(TEST_VIDEO_ID)
    assert len(calls) == 1


async def test_cookie_outside_fence_rejected_before_spawn(download_dir, tmp_path, monkeypatch):
    cookie = tmp_path / 'outside.cookies'
    cookie.write_bytes(b'cookie')
    monkeypatch.setenv('MEDIA_COOKIES_FILE', str(cookie))
    monkeypatch.setenv('LOCAL_FILE_ACCESS_ROOT', str(tmp_path / 'allowed'))
    calls = downloader(monkeypatch)
    with pytest.raises(ValueError, match='LOCAL_FILE_ACCESS_ROOT'):
        await module.download_youtube_video(TEST_VIDEO_ID)
    assert calls == []


async def test_cache_symlink_rejected_without_reading_target(download_dir, tmp_path, monkeypatch):
    original = tmp_path / 'original'
    original.write_bytes(b'keep')
    (download_dir / f'{TEST_VIDEO_ID}.mp4').symlink_to(original)
    calls = downloader(monkeypatch)
    with pytest.raises(ValueError, match='symlinks'):
        await module.download_youtube_video(TEST_VIDEO_ID)
    assert calls == []
    assert original.read_bytes() == b'keep'


async def test_target_dir_and_simultaneous_reuse(tmp_path, monkeypatch):
    target = tmp_path / 'nested' / 'media'
    calls = downloader(monkeypatch)
    monkeypatch.setattr(module.shutil, 'which', lambda _: '/fixture/yt-dlp')
    paths = await asyncio.gather(*(module.download_youtube_video(TEST_VIDEO_ID, target_dir=target) for _ in range(2)))
    assert paths == [target / f'{TEST_VIDEO_ID}.mp4'] * 2
    assert len(calls) == 1


@pytest.mark.skipif(os.name != 'posix', reason='POSIX named pipes')
async def test_fifo_cache_and_receipt_rejected_without_blocked_worker(download_dir, monkeypatch):
    output = download_dir / f'{TEST_VIDEO_ID}.mp4'
    calls = downloader(monkeypatch)
    os.mkfifo(output)
    with pytest.raises(ValueError, match='regular file'):
        await asyncio.wait_for(module.download_youtube_video(TEST_VIDEO_ID), 1)
    assert output.is_fifo() and calls == []
    output.unlink()
    output.write_bytes(b'fixture')
    sidecar = output.with_suffix('.receipt.json')
    os.mkfifo(sidecar)
    with pytest.raises(ValueError, match='provenance is unknown'):
        await asyncio.wait_for(module.download_youtube_video(TEST_VIDEO_ID), 1)
    assert sidecar.is_fifo() and output.read_bytes() == b'fixture' and calls == []
