"""Tests for YouTube Data API client and tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import video_research_mcp.config as cfg_mod

import pytest

from video_research_mcp.models.youtube import (
    PlaylistInfo,
    PlaylistItem,
    VideoMetadata,
    YOUTUBE_CATEGORIES,
)
from video_research_mcp.youtube import (
    YouTubeClient,
    _format_duration,
    _parse_iso8601_duration,
)


# ── Duration parsing ────────────────────────────────────────────────────────


class TestParseIso8601Duration:
    """ISO 8601 duration string → seconds."""

    def test_minutes_and_seconds(self):
        assert _parse_iso8601_duration("PT4M13S") == 253

    def test_hours_minutes_seconds(self):
        assert _parse_iso8601_duration("PT1H2M3S") == 3723

    def test_hours_only(self):
        assert _parse_iso8601_duration("PT2H") == 7200

    def test_seconds_only(self):
        assert _parse_iso8601_duration("PT45S") == 45

    def test_minutes_only(self):
        assert _parse_iso8601_duration("PT10M") == 600

    def test_empty_string(self):
        assert _parse_iso8601_duration("") == 0

    def test_none_value(self):
        assert _parse_iso8601_duration(None) == 0

    def test_invalid_format(self):
        assert _parse_iso8601_duration("not-a-duration") == 0


class TestFormatDuration:
    """Seconds → human-readable display string."""

    def test_short_video(self):
        assert _format_duration(253) == "4:13"

    def test_long_video(self):
        assert _format_duration(3723) == "1:02:03"

    def test_zero(self):
        assert _format_duration(0) == "0:00"

    def test_exact_minute(self):
        assert _format_duration(60) == "1:00"

    def test_under_minute(self):
        assert _format_duration(9) == "0:09"


# ── YouTubeClient ───────────────────────────────────────────────────────────


def _mock_videos_response(video_id: str = "dQw4w9WgXcQ") -> dict:
    """Build a realistic YouTube videos.list response."""
    return {
        "items": [{
            "snippet": {
                "title": "Rick Astley - Never Gonna Give You Up",
                "description": "The official video for...",
                "channelId": "UCuAXFkgsw1L7xaCfnd5JJOw",
                "channelTitle": "Rick Astley",
                "publishedAt": "2009-10-25T06:57:33Z",
                "categoryId": "10",
                "tags": ["rick astley", "never gonna give you up"],
                "defaultLanguage": "en",
            },
            "contentDetails": {
                "duration": "PT3M33S",
                "definition": "hd",
                "caption": "true",
            },
            "statistics": {
                "viewCount": "1500000000",
                "likeCount": "16000000",
                "commentCount": "3000000",
            },
        }]
    }


def _mock_empty_response() -> dict:
    return {"items": []}


def _mock_playlist_response(playlist_id: str = "PLtest") -> dict:
    return {
        "pageInfo": {"totalResults": 3},
        "items": [
            {
                "snippet": {
                    "title": "Video One",
                    "position": 0,
                    "publishedAt": "2024-01-01T00:00:00Z",
                    "resourceId": {"videoId": "vid1"},
                },
            },
            {
                "snippet": {
                    "title": "Video Two",
                    "position": 1,
                    "publishedAt": "2024-01-02T00:00:00Z",
                    "resourceId": {"videoId": "vid2"},
                },
            },
        ],
    }


@pytest.fixture(autouse=True)
def _reset_youtube_client():
    """Reset singleton between tests."""
    YouTubeClient.reset()
    yield
    YouTubeClient.reset()


@pytest.fixture()
def mock_youtube_service():
    """Provide a mocked YouTube API service."""
    service = MagicMock()
    with patch("video_research_mcp.youtube.YouTubeClient.get", return_value=service):
        yield service


class TestVideoMetadata:
    """YouTubeClient.video_metadata() tests."""

    async def test_returns_metadata(self, mock_youtube_service):
        """GIVEN a valid video ID WHEN fetching metadata THEN returns VideoMetadata."""
        mock_youtube_service.videos().list().execute.return_value = (
            _mock_videos_response()
        )

        meta = await YouTubeClient.video_metadata("dQw4w9WgXcQ")

        assert isinstance(meta, VideoMetadata)
        assert meta.title == "Rick Astley - Never Gonna Give You Up"
        assert meta.view_count == 1_500_000_000
        assert meta.duration_seconds == 213
        assert meta.duration_display == "3:33"
        assert meta.category == "Music"
        assert meta.has_captions is True
        assert meta.definition == "hd"
        assert "rick astley" in meta.tags

    async def test_empty_response_raises(self, mock_youtube_service):
        """GIVEN empty items WHEN video_metadata THEN ValueError raised."""
        mock_youtube_service.videos().list().execute.return_value = (
            _mock_empty_response()
        )

        with pytest.raises(ValueError, match="Video not found"):
            await YouTubeClient.video_metadata("INVALID_ID")


class TestVideoComments:
    """YouTubeClient.video_comments() tests."""

    async def test_returns_comments(self, mock_youtube_service):
        """GIVEN a video with comments WHEN fetching THEN returns comment list."""
        mock_youtube_service.commentThreads().list().execute.return_value = {
            "items": [
                {
                    "snippet": {
                        "topLevelComment": {
                            "snippet": {
                                "textDisplay": "Great video!",
                                "likeCount": 42,
                                "authorDisplayName": "Alice",
                            }
                        }
                    }
                },
                {
                    "snippet": {
                        "topLevelComment": {
                            "snippet": {
                                "textDisplay": "Nice",
                                "likeCount": 0,
                                "authorDisplayName": "Bob",
                            }
                        }
                    }
                },
            ]
        }
        mock_youtube_service.commentThreads().list_next.return_value = None

        comments = await YouTubeClient.video_comments("abc123", max_comments=10)

        assert len(comments) == 2
        assert comments[0]["text"] == "Great video!"
        assert comments[0]["likes"] == 42
        assert comments[1]["author"] == "Bob"

    async def test_missing_fields_use_defaults(self, mock_youtube_service):
        """GIVEN a comment with missing fields WHEN fetching THEN uses safe defaults."""
        mock_youtube_service.commentThreads().list().execute.return_value = {
            "items": [{"snippet": {"topLevelComment": {"snippet": {}}}}]
        }
        mock_youtube_service.commentThreads().list_next.return_value = None

        comments = await YouTubeClient.video_comments("abc123", max_comments=10)

        assert len(comments) == 1
        assert comments[0]["text"] == ""
        assert comments[0]["likes"] == 0
        assert comments[0]["author"] == ""


class TestPlaylistItems:
    """YouTubeClient.playlist_items() tests."""

    async def test_returns_playlist(self, mock_youtube_service):
        """GIVEN a valid playlist WHEN fetching THEN returns PlaylistInfo."""
        list_mock = mock_youtube_service.playlistItems().list()
        list_mock.execute.return_value = _mock_playlist_response()
        mock_youtube_service.playlistItems().list_next.return_value = None

        info = await YouTubeClient.playlist_items("PLtest", max_items=10)

        assert isinstance(info, PlaylistInfo)
        assert info.playlist_id == "PLtest"
        assert info.total_items == 3
        assert len(info.items) == 2
        assert info.items[0].video_id == "vid1"
        assert info.items[1].title == "Video Two"


# ── Tool functions ──────────────────────────────────────────────────────────


class TestVideoMetadataTool:
    """video_metadata() MCP tool tests."""

    async def test_valid_url(self, mock_youtube_service):
        """GIVEN a YouTube URL WHEN calling tool THEN returns metadata dict."""
        from video_research_mcp.tools.youtube import video_metadata

        mock_youtube_service.videos().list().execute.return_value = (
            _mock_videos_response()
        )

        result = await video_metadata(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )

        assert result["title"] == "Rick Astley - Never Gonna Give You Up"
        assert result["video_id"] == "dQw4w9WgXcQ"
        assert "error" not in result

    async def test_invalid_url(self):
        """GIVEN a non-YouTube URL WHEN calling tool THEN returns error."""
        from video_research_mcp.tools.youtube import video_metadata

        result = await video_metadata(url="https://example.com/not-youtube")

        assert "error" in result
        assert "category" in result

    async def test_invalid_video_id_returns_error(self):
        """GIVEN invalid video ID WHEN video_metadata tool called THEN structured error returned."""
        with patch.object(YouTubeClient, "video_metadata", new_callable=AsyncMock) as mock_meta:
            mock_meta.side_effect = ValueError("Video not found: INVALID_ID")

            from video_research_mcp.tools.youtube import video_metadata

            result = await video_metadata(url="https://www.youtube.com/watch?v=INVALID_ID")

            assert "error" in result
            assert "Video not found" in result["error"]
            assert "category" in result
            assert "retryable" in result

    async def test_api_403_returns_youtube_hint(self, mock_youtube_service):
        """GIVEN a 403 HttpError WHEN calling tool THEN returns YouTube-specific hint."""
        from googleapiclient.errors import HttpError
        from video_research_mcp.tools.youtube import video_metadata

        resp = MagicMock()
        resp.status = 403
        mock_youtube_service.videos().list().execute.side_effect = (
            HttpError(resp, b"forbidden")
        )

        result = await video_metadata(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )

        assert "error" in result
        assert result["category"] == "API_PERMISSION_DENIED"
        assert "YOUTUBE_API_KEY" in result["hint"]
        assert "console.cloud.google.com" in result["hint"]


class TestVideoCommentsTool:
    """video_comments() MCP tool tests."""

    async def test_valid_url(self, mock_youtube_service):
        """GIVEN a YouTube URL WHEN calling tool THEN returns comments dict."""
        from video_research_mcp.tools.youtube import video_comments

        mock_youtube_service.commentThreads().list().execute.return_value = {
            "items": [
                {
                    "snippet": {
                        "topLevelComment": {
                            "snippet": {
                                "textDisplay": "Great video!",
                                "likeCount": 42,
                                "authorDisplayName": "Alice",
                            }
                        }
                    }
                },
            ]
        }
        mock_youtube_service.commentThreads().list_next.return_value = None

        result = await video_comments(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )

        assert result["video_id"] == "dQw4w9WgXcQ"
        assert result["count"] == 1
        assert result["comments"][0]["text"] == "Great video!"
        assert "error" not in result

    async def test_invalid_url(self):
        """GIVEN a non-YouTube URL WHEN calling tool THEN returns error."""
        from video_research_mcp.tools.youtube import video_comments

        result = await video_comments(url="https://example.com/not-youtube")

        assert "error" in result
        assert "category" in result

    async def test_api_403_returns_hint(self, mock_youtube_service):
        """GIVEN a 403 HttpError WHEN calling tool THEN returns YOUTUBE_API_KEY hint."""
        from googleapiclient.errors import HttpError
        from video_research_mcp.tools.youtube import video_comments

        resp = MagicMock()
        resp.status = 403
        mock_youtube_service.commentThreads().list().execute.side_effect = (
            HttpError(resp, b"forbidden")
        )

        result = await video_comments(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )

        assert "error" in result
        assert result["category"] == "API_PERMISSION_DENIED"
        assert "YOUTUBE_API_KEY" in result["hint"]
        assert "console.cloud.google.com" in result["hint"]


class TestVideoPlaylistTool:
    """video_playlist() MCP tool tests."""

    async def test_valid_playlist(self, mock_youtube_service):
        """GIVEN a playlist URL WHEN calling tool THEN returns playlist info."""
        from video_research_mcp.tools.youtube import video_playlist

        list_mock = mock_youtube_service.playlistItems().list()
        list_mock.execute.return_value = _mock_playlist_response()
        mock_youtube_service.playlistItems().list_next.return_value = None

        result = await video_playlist(
            url="https://www.youtube.com/playlist?list=PLtest123"
        )

        assert result["playlist_id"] == "PLtest123"
        assert len(result["items"]) == 2
        assert "error" not in result

    async def test_no_list_param(self):
        """GIVEN a URL without list param WHEN calling tool THEN returns error."""
        from video_research_mcp.tools.youtube import video_playlist

        result = await video_playlist(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )

        assert "error" in result


class TestPlaylistIdExtraction:
    """_extract_playlist_id() tests."""

    def test_standard_playlist_url(self):
        from video_research_mcp.tools.youtube import _extract_playlist_id

        pid = _extract_playlist_id(
            "https://www.youtube.com/playlist?list=PLrAXtmErZgOe"
        )
        assert pid == "PLrAXtmErZgOe"

    def test_video_with_playlist(self):
        from video_research_mcp.tools.youtube import _extract_playlist_id

        pid = _extract_playlist_id(
            "https://www.youtube.com/watch?v=abc&list=PLxyz123"
        )
        assert pid == "PLxyz123"

    def test_no_list_param_raises(self):
        from video_research_mcp.tools.youtube import _extract_playlist_id

        with pytest.raises(ValueError, match="playlist ID"):
            _extract_playlist_id("https://www.youtube.com/watch?v=abc")

    def test_rejects_spoofed_domain(self):
        from video_research_mcp.tools.youtube import _extract_playlist_id

        with pytest.raises(ValueError, match="Not a YouTube URL"):
            _extract_playlist_id("https://evil.com/playlist?list=PLmalicious")


# ── Session creation optimization ───────────────────────────────────────────


class TestSessionCreationOptimization:
    """video_create_session uses YouTube API instead of Gemini for titles."""

    async def test_youtube_url_uses_youtube_api(self, mock_gemini_client, mock_youtube_service):
        """GIVEN a YouTube URL WHEN creating session THEN uses YouTube API, not Gemini."""
        from video_research_mcp.tools.video import video_create_session

        mock_youtube_service.videos().list().execute.return_value = (
            _mock_videos_response()
        )

        result = await video_create_session(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )

        assert result["video_title"] == "Rick Astley - Never Gonna Give You Up"
        assert result["source_type"] == "youtube"
        mock_gemini_client["generate"].assert_not_called()

    async def test_youtube_api_failure_falls_back_to_gemini(
        self, mock_gemini_client, mock_youtube_service
    ):
        """GIVEN YouTube API fails WHEN creating session THEN falls back to Gemini."""
        from video_research_mcp.tools.video import video_create_session

        mock_youtube_service.videos().list().execute.side_effect = Exception("quota")
        mock_gemini_client["generate"].return_value = "Fallback Title"

        result = await video_create_session(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )

        assert result["video_title"] == "Fallback Title"
        mock_gemini_client["generate"].assert_called_once()


# ── Model tests ─────────────────────────────────────────────────────────────


class TestVideoMetadataModel:
    """VideoMetadata Pydantic model tests."""

    def test_defaults(self):
        meta = VideoMetadata(video_id="test")
        assert meta.title == ""
        assert meta.view_count == 0
        assert meta.tags == []

    def test_roundtrip(self):
        meta = VideoMetadata(
            video_id="abc",
            title="Test",
            view_count=100,
            tags=["a", "b"],
        )
        data = meta.model_dump()
        restored = VideoMetadata(**data)
        assert restored == meta


class TestPlaylistModels:
    """Playlist Pydantic model tests."""

    def test_playlist_info_defaults(self):
        info = PlaylistInfo(playlist_id="PL123")
        assert info.items == []
        assert info.total_items == 0

    def test_playlist_item_roundtrip(self):
        item = PlaylistItem(video_id="v1", title="First", position=0)
        assert PlaylistItem(**item.model_dump()) == item


class TestYouTubeCategories:
    """Category constant coverage."""

    def test_music_category(self):
        assert YOUTUBE_CATEGORIES["10"] == "Music"

    def test_education_category(self):
        assert YOUTUBE_CATEGORIES["27"] == "Education"

    def test_science_tech_category(self):
        assert YOUTUBE_CATEGORIES["28"] == "Science & Technology"


# ── API key fallback ───────────────────────────────────────────────────────


class TestYouTubeApiKeyFallback:
    """YouTube API key selection logic."""

    def test_uses_dedicated_key_when_set(self, monkeypatch):
        """GIVEN youtube_api_key is set WHEN get() is called THEN uses youtube_api_key."""
        monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
        monkeypatch.setenv("YOUTUBE_API_KEY", "yt-key")
        cfg_mod._config = None
        YouTubeClient.reset()
        with patch("video_research_mcp.youtube.get_config") as mock_cfg:
            from video_research_mcp.config import ServerConfig
            mock_cfg.return_value = ServerConfig(
                gemini_api_key="gemini-key",
                youtube_api_key="yt-key",
            )
            with patch("googleapiclient.discovery.build") as mock_build:
                YouTubeClient.get()
                mock_build.assert_called_once_with(
                    "youtube", "v3", developerKey="yt-key", cache_discovery=False,
                )
        YouTubeClient.reset()

    def test_falls_back_to_gemini_key_when_empty(self, monkeypatch):
        """GIVEN youtube_api_key is empty WHEN get() is called THEN uses gemini_api_key."""
        monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
        cfg_mod._config = None
        YouTubeClient.reset()
        with patch("video_research_mcp.youtube.get_config") as mock_cfg:
            from video_research_mcp.config import ServerConfig
            mock_cfg.return_value = ServerConfig(
                gemini_api_key="gemini-key",
                youtube_api_key="",
            )
            with patch("googleapiclient.discovery.build") as mock_build:
                YouTubeClient.get()
                mock_build.assert_called_once_with(
                    "youtube", "v3", developerKey="gemini-key", cache_discovery=False,
                )
        YouTubeClient.reset()


def test_data_api_permission_error_redacts_keys_and_credentials():
    """New channel tools reuse the existing 403 boundary without exposing SDK URLs."""
    from googleapiclient.errors import HttpError
    from httplib2 import Response
    from video_research_mcp.tools.youtube import _youtube_api_error

    exc = HttpError(
        Response({'status': '403'}),
        b'{"error":{"message":"API key denied; token=owned-sensitive-fixture"}}',
        uri='https://youtube.googleapis.com/youtube/v3/channels?key=owned-query-key',
    )
    result = _youtube_api_error(exc)
    assert result['category'] == 'API_PERMISSION_DENIED'
    assert result['retryable'] is False
    assert 'owned-query-key' not in result['error']
    assert 'owned-sensitive-fixture' not in result['error']
    assert 'youtube.googleapis.com/youtube/v3/channels' in result['error']
