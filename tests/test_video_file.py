"""Tests for video file helpers — MIME detection, hashing, content building, upload cache."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from video_research_mcp.tools.video_file import (
    LARGE_FILE_THRESHOLD,
    SUPPORTED_VIDEO_EXTENSIONS,
    _file_content_hash,
    _validate_video_path,
    _video_file_content,
    _video_file_uri,
    _video_mime_type,
    _wait_for_active,
)


def _mock_upload_result(uri="https://generativelanguage.googleapis.com/v1/files/abc123",
                        name="files/abc123", state="PROCESSING"):
    """Create a mock upload result with required attributes."""
    uploaded = MagicMock()
    uploaded.uri = uri
    uploaded.name = name
    uploaded.state = state
    return uploaded


class TestVideoMimeType:
    def test_supported_extensions(self):
        for ext, mime in SUPPORTED_VIDEO_EXTENSIONS.items():
            assert _video_mime_type(Path(f"video{ext}")) == mime

    def test_case_insensitive(self):
        assert _video_mime_type(Path("video.MP4")) == "video/mp4"
        assert _video_mime_type(Path("video.WebM")) == "video/webm"

    def test_unsupported_extension(self):
        with pytest.raises(ValueError, match="Unsupported video extension"):
            _video_mime_type(Path("file.txt"))

    def test_no_extension(self):
        with pytest.raises(ValueError, match="Unsupported video extension"):
            _video_mime_type(Path("noextension"))


class TestFileContentHash:
    def test_deterministic(self, tmp_path):
        f = tmp_path / "test.mp4"
        f.write_bytes(b"video content")
        h1 = _file_content_hash(f)
        h2 = _file_content_hash(f)
        assert h1 == h2
        assert len(h1) == 64
        assert h1 == hashlib.sha256(f.read_bytes()).hexdigest()

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.mp4"
        f2 = tmp_path / "b.mp4"
        f1.write_bytes(b"content A")
        f2.write_bytes(b"content B")
        assert _file_content_hash(f1) != _file_content_hash(f2)

    def test_streaming_growth_exceeding_byte_ceiling_is_rejected(
        self, tmp_path, monkeypatch, clean_config
    ):
        source = tmp_path / "growing.mp4"
        source.write_bytes(b"short")
        monkeypatch.setenv("MEDIA_MAX_INPUT_BYTES", "5")
        from video_research_mcp import media_local_io
        original = media_local_io._open_regular

        def growing_reader(path):
            reader = original(path)
            old_read = reader.read

            def read_and_grow(size):
                result = old_read(size)
                with source.open("ab") as writer:
                    writer.write(b"growth")
                return result

            reader.read = read_and_grow
            return reader

        monkeypatch.setattr(media_local_io, "_open_regular", growing_reader)
        with pytest.raises(ValueError, match="changed while reading"):
            _file_content_hash(source)


class TestValidateVideoPath:
    def test_valid_file(self, tmp_path):
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"\x00" * 10)
        p, mime = _validate_video_path(str(f))
        assert p == f
        assert mime == "video/mp4"

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Video file not found"):
            _validate_video_path(str(tmp_path / "missing.mp4"))

    def test_not_a_file(self, tmp_path):
        d = tmp_path / "subdir"
        d.mkdir()
        with pytest.raises(ValueError, match="Not a file"):
            _validate_video_path(str(d))

    def test_unsupported_extension(self, tmp_path):
        f = tmp_path / "readme.txt"
        f.write_text("hello")
        with pytest.raises(ValueError, match="Unsupported video extension"):
            _validate_video_path(str(f))

    def test_rejects_path_outside_local_access_root(self, tmp_path, monkeypatch, clean_config):
        root = tmp_path / "allowed"
        root.mkdir()
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"\x00" * 10)
        monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(root))

        with pytest.raises(PermissionError, match="outside LOCAL_FILE_ACCESS_ROOT"):
            _validate_video_path(str(outside))


class TestVideoFileContent:
    @pytest.mark.parametrize("uploaded", [False, True])
    async def test_actual_sdk_request_contains_window_metadata(self, tmp_path, monkeypatch, mock_gemini_client, uploaded):
        import httpx
        from google import genai
        from google.genai import types

        source = tmp_path / "window.mp4"
        source.write_bytes(b"owned video bytes")
        monkeypatch.setattr("video_research_mcp.tools.video_file.LARGE_FILE_THRESHOLD", 1 if uploaded else 1000)
        mock_gemini_client["client"].aio.files.upload = AsyncMock(return_value=_mock_upload_result())
        mock_gemini_client["client"].aio.files.get = AsyncMock(return_value=_mock_upload_result(state="ACTIVE"))
        metadata = types.VideoMetadata(start_offset="1.5s", end_offset="3.25s", fps=2.5)
        content, _, _ = await _video_file_content(str(source), "inspect", video_metadata=metadata)
        requests = []

        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}], "role": "model"}}]})

        transport = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client = genai.Client(api_key="fixture-key", http_options=types.HttpOptions(httpx_async_client=transport))
        try:
            await client.aio.models.generate_content(model="fixture-model", contents=[content])
        finally:
            await client.aio.aclose()
        part = requests[0]["contents"][0]["parts"][0]
        assert part["videoMetadata"] == {"start_offset": "1.5s", "end_offset": "3.25s", "fps": 2.5}
        assert part["mediaProcessing"] == "STATIC"
        assert ("fileData" in part) is uploaded

    async def test_byte_ceiling_precedes_hash_read_upload(self, tmp_path, monkeypatch, clean_config):
        f = tmp_path / "large.mp4"
        f.write_bytes(b"0123456789")
        monkeypatch.setenv("MEDIA_MAX_INPUT_BYTES", "9")
        hash_mock = MagicMock(side_effect=AssertionError("hashing must not start"))
        monkeypatch.setattr("video_research_mcp.tools.video_file._file_content_hash", hash_mock)
        with pytest.raises(ValueError, match="MEDIA_MAX_INPUT_BYTES"):
            await _video_file_content(str(f), "analyze")
        hash_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_small_file_uses_inline_bytes(self, tmp_path, mock_gemini_client):
        """Files under threshold use Part.from_bytes (no File API upload)."""
        f = tmp_path / "small.mp4"
        f.write_bytes(b"\x00" * 100)

        content, content_id, file_uri = await _video_file_content(str(f), "summarize")

        assert content_id == _file_content_hash(f)
        assert file_uri == ""  # small files use inline bytes, no File API URI
        assert len(content.parts) == 2
        # First part: inline bytes (no file_data attribute)
        assert content.parts[0].inline_data is not None
        # Second part: text prompt
        assert content.parts[1].text == "summarize"

    @pytest.mark.asyncio
    async def test_large_file_uses_file_api(self, tmp_path, mock_gemini_client):
        """Files at or above threshold upload via File API."""
        f = tmp_path / "big.mp4"
        f.write_bytes(b"\x00" * LARGE_FILE_THRESHOLD)

        uploaded = _mock_upload_result()
        mock_gemini_client["client"].aio.files.upload = AsyncMock(return_value=uploaded)
        active_file = _mock_upload_result(state="ACTIVE")
        mock_gemini_client["client"].aio.files.get = AsyncMock(return_value=active_file)

        content, content_id, file_uri = await _video_file_content(str(f), "analyze")

        assert content.parts[0].file_data.file_uri == uploaded.uri
        assert file_uri == uploaded.uri  # large files return File API URI
        assert content.parts[1].text == "analyze"
        mock_gemini_client["client"].aio.files.upload.assert_called_once()

    @pytest.mark.asyncio
    async def test_file_not_found(self, mock_gemini_client):
        with pytest.raises(FileNotFoundError):
            await _video_file_content("/nonexistent/video.mp4", "test")


class TestVideoFileUri:
    @pytest.mark.asyncio
    async def test_always_uploads(self, tmp_path, mock_gemini_client):
        """Sessions always upload to get a stable URI, even for small files."""
        f = tmp_path / "tiny.mp4"
        f.write_bytes(b"\x00" * 50)

        uploaded = _mock_upload_result(
            uri="https://generativelanguage.googleapis.com/v1/files/xyz",
            name="files/xyz",
        )
        mock_gemini_client["client"].aio.files.upload = AsyncMock(return_value=uploaded)
        active_file = _mock_upload_result(uri=uploaded.uri, name=uploaded.name, state="ACTIVE")
        mock_gemini_client["client"].aio.files.get = AsyncMock(return_value=active_file)

        uri, content_id = await _video_file_uri(str(f))

        assert uri == uploaded.uri
        assert content_id == _file_content_hash(f)
        mock_gemini_client["client"].aio.files.upload.assert_called_once()


class TestWaitForActive:
    @pytest.mark.asyncio
    async def test_immediate_active(self, mock_gemini_client):
        """Returns immediately when file is already ACTIVE."""
        client = mock_gemini_client["client"]
        client.aio.files.get = AsyncMock(return_value=MagicMock(state="ACTIVE"))

        await _wait_for_active(client, "files/abc123")

        client.aio.files.get.assert_called_once()
        args = client.aio.files.get.call_args.kwargs
        assert args["name"] == "files/abc123"
        assert 0 < args["config"].http_options.timeout <= 120000
        assert args["config"].http_options.retry_options.attempts == 1

    @pytest.mark.asyncio
    async def test_processing_then_active(self, mock_gemini_client):
        """Polls through PROCESSING state until ACTIVE."""
        client = mock_gemini_client["client"]
        client.aio.files.get = AsyncMock(side_effect=[
            MagicMock(state="PROCESSING"),
            MagicMock(state="PROCESSING"),
            MagicMock(state="ACTIVE"),
        ])

        await _wait_for_active(client, "files/abc123", interval=0.01)

        assert client.aio.files.get.call_count == 3

    @pytest.mark.asyncio
    async def test_failed_state_raises(self, mock_gemini_client):
        """Raises RuntimeError immediately on FAILED state."""
        client = mock_gemini_client["client"]
        client.aio.files.get = AsyncMock(return_value=MagicMock(state="FAILED"))

        with pytest.raises(RuntimeError, match="File processing failed"):
            await _wait_for_active(client, "files/abc123")

    @pytest.mark.asyncio
    async def test_timeout_raises(self, mock_gemini_client):
        """Raises TimeoutError when file stays PROCESSING past deadline."""
        client = mock_gemini_client["client"]
        client.aio.files.get = AsyncMock(return_value=MagicMock(state="PROCESSING"))

        with pytest.raises(TimeoutError, match="not active after"):
            await _wait_for_active(client, "files/abc123", timeout=0.05, interval=0.01)

