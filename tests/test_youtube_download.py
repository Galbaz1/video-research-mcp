"""Tests for YouTube download via yt-dlp subprocess wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import video_research_mcp.config as cfg_mod
from video_research_mcp.tools.youtube_download import download_youtube_video

TEST_VIDEO_ID = "dQw4w9WgXcQ"


@pytest.fixture(autouse=True)
def _clean_config(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    cfg_mod._config = None
    yield
    cfg_mod._config = None


@pytest.fixture()
def download_dir(tmp_path, monkeypatch):
    """Redirect download directory to a temp path."""
    dl_dir = tmp_path / "downloads"
    dl_dir.mkdir()
    monkeypatch.setattr(
        "video_research_mcp.tools.youtube_download._download_dir",
        lambda: dl_dir,
    )
    return dl_dir


class TestDownloadYoutubeVideo:
    @pytest.mark.parametrize("video_id", ["../outside", "file:///etc/passwd", "https://example.org", "--exec=bad"])
    async def test_invalid_id_rejected_before_filesystem_or_process(self, video_id, tmp_path):
        target = tmp_path / "not-created"
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
            with pytest.raises(ValueError, match="eleven-character"):
                await download_youtube_video(video_id, target_dir=target)
        assert not target.exists()
        spawn.assert_not_called()

    async def test_all_format_branches_keep_dimension_ceiling(self, download_dir):
        output = download_dir / f"{TEST_VIDEO_ID}.mp4"
        proc = MagicMock(returncode=0)
        proc.communicate = AsyncMock(return_value=(b"", b""))

        async def spawn(*args, **kwargs):
            formats = args[args.index("-f") + 1].split("/")
            assert all("[height<=720]" in f and "[width<=1280]" in f for f in formats)
            assert "--ignore-config" in args
            assert "--max-filesize" in args
            output.write_bytes(b"video")
            return proc

        with patch("shutil.which", return_value="yt-dlp"), patch("asyncio.create_subprocess_exec", side_effect=spawn):
            await download_youtube_video(TEST_VIDEO_ID)

    async def test_oversized_cached_download_never_reaches_subprocess(self, download_dir, monkeypatch):
        monkeypatch.setenv("MEDIA_MAX_INPUT_BYTES", "9")
        (download_dir / f"{TEST_VIDEO_ID}.mp4").write_bytes(b"0123456789")
        with patch("shutil.which", return_value="yt-dlp"), patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
            with pytest.raises(ValueError, match="MEDIA_MAX_INPUT_BYTES"):
                await download_youtube_video(TEST_VIDEO_ID)
        spawn.assert_not_called()

    async def test_raises_when_ytdlp_not_found(self, download_dir):
        """GIVEN yt-dlp not installed WHEN download called THEN raises RuntimeError."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="yt-dlp not found"):
                await download_youtube_video(TEST_VIDEO_ID)

    async def test_returns_cached_download(self, download_dir):
        """GIVEN file already exists WHEN download called THEN skips re-download."""
        cached_file = download_dir / f"{TEST_VIDEO_ID}.mp4"
        cached_file.write_bytes(b"fake video content")

        with patch("shutil.which", return_value="/usr/bin/yt-dlp"):
            result = await download_youtube_video(TEST_VIDEO_ID)

        assert result == cached_file

    async def test_download_succeeds(self, download_dir):
        """GIVEN yt-dlp succeeds WHEN download called THEN returns path to file."""
        output_path = download_dir / f"{TEST_VIDEO_ID}.mp4"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        async def fake_subprocess(*args, **kwargs):
            # Simulate yt-dlp writing the output file
            output_path.write_bytes(b"downloaded video data")
            return mock_proc

        with (
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
            patch(
                "asyncio.create_subprocess_exec",
                side_effect=fake_subprocess,
            ),
        ):
            result = await download_youtube_video(TEST_VIDEO_ID)

        assert result == output_path
        assert result.exists()

    async def test_download_fails_with_error(self, download_dir):
        """GIVEN yt-dlp exits with error WHEN download called THEN raises RuntimeError."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Video unavailable"))

        with (
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
            patch(
                "asyncio.create_subprocess_exec",
                AsyncMock(return_value=mock_proc),
            ),
        ):
            with pytest.raises(RuntimeError, match="Video unavailable"):
                await download_youtube_video(TEST_VIDEO_ID)

    async def test_skips_empty_cached_file(self, download_dir):
        """GIVEN an empty cached file WHEN download called THEN re-downloads."""
        cached_file = download_dir / f"{TEST_VIDEO_ID}.mp4"
        cached_file.write_bytes(b"")  # empty = partial/failed download

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        async def fake_subprocess(*args, **kwargs):
            cached_file.write_bytes(b"fresh download")
            return mock_proc

        with (
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
            patch(
                "asyncio.create_subprocess_exec",
                side_effect=fake_subprocess,
            ),
        ):
            result = await download_youtube_video(TEST_VIDEO_ID)

        assert result == cached_file
        assert result.read_bytes() == b"fresh download"

    async def test_uses_target_dir_when_provided(self, tmp_path):
        """GIVEN target_dir WHEN download called THEN writes output in that directory."""
        target_dir = tmp_path / "media" / "videos"
        output_path = target_dir / f"{TEST_VIDEO_ID}.mp4"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        async def fake_subprocess(*args, **kwargs):
            output_path.write_bytes(b"downloaded video data")
            return mock_proc

        with (
            patch("shutil.which", return_value="/usr/bin/yt-dlp"),
            patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess),
        ):
            result = await download_youtube_video(TEST_VIDEO_ID, target_dir=target_dir)

        assert target_dir.exists()
        assert result == output_path
        assert result.exists()
