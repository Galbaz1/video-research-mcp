"""Offline channel identity, bounded catalog and actual MCP contract tests."""

from copy import deepcopy
import json
from pathlib import Path
import socket
import subprocess
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

from fastmcp import Client
from googleapiclient import discovery_cache
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from httplib2 import Response
from jsonschema import validate
import pytest

from video_research_mcp.tools.youtube_channels import (
    youtube_channel_catalog,
    youtube_channel_inspect,
)
from video_research_mcp.youtube import YouTubeClient
from video_research_mcp.youtube_channels import (
    channel_catalog,
    channel_metadata,
    channel_selector,
)

CHANNEL_ID = "UC" + "a" * 22
OTHER_CHANNEL_ID = "UC" + "b" * 22
HANDLE = "@owned.channel"
PLAYLIST_ID = "UU" + "a" * 22
VIDEO_ID = "Abcdefgh_12"


def channel_response():
    """Return original fixture metadata with explicit provider counters."""
    return {
        "items": [{
            "id": CHANNEL_ID,
            "snippet": {
                "title": "Owned fixture channel", "description": "Original test metadata",
                "publishedAt": "2026-01-01T00:00:00Z", "customUrl": HANDLE,
                "thumbnails": {"default": {"url": "https://example.invalid/preview.png"}},
                "country": "NL",
            },
            "statistics": {
                "subscriberCount": "17", "hiddenSubscriberCount": False,
                "videoCount": "123", "viewCount": "456",
            },
            "contentDetails": {"relatedPlaylists": {"uploads": PLAYLIST_ID}},
        }],
    }


def catalog_response(count=2):
    """Return one owned uploads page with a distinct reported total."""
    return {
        "items": [{"snippet": {
            "resourceId": {"videoId": VIDEO_ID}, "title": f"Owned video {index}",
            "position": index, "publishedAt": "2026-01-02T00:00:00Z",
        }} for index in range(count)],
        "pageInfo": {"totalResults": 123}, "nextPageToken": "next-owned-page",
    }


@pytest.fixture(autouse=True)
def forbidden_external_effects(monkeypatch, clean_config):
    """Fail before any network, process, Gemini, download or upload operation."""
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append("unexpected external operation")
        raise AssertionError("Channel tests forbid external I/O and media/provider work")

    monkeypatch.setenv("WEAVIATE_URL", "")
    monkeypatch.setenv("FASTMCP_CHECK_FOR_UPDATES", "off")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(YouTubeClient, "get", forbidden)
    monkeypatch.setattr("video_research_mcp.client.GeminiClient.get", forbidden)
    monkeypatch.setattr("video_research_mcp.client.GeminiClient.generate", AsyncMock(side_effect=forbidden))
    monkeypatch.setattr("video_research_mcp.client.GeminiClient.generate_structured", AsyncMock(side_effect=forbidden))
    monkeypatch.setattr("video_research_mcp.tools.youtube_download.download_youtube_video", AsyncMock(side_effect=forbidden))
    monkeypatch.setattr("video_research_mcp.tools.video_file._upload_large_file", AsyncMock(side_effect=forbidden))
    yield attempts
    assert not attempts


@pytest.fixture
def service(monkeypatch):
    """Replace only the external Data API service; execute actual controller code."""
    service = MagicMock(name="owned_mock_youtube_service")
    service.channels.return_value.list.return_value.execute.return_value = channel_response()
    service.playlistItems.return_value.list.return_value.execute.return_value = catalog_response()
    monkeypatch.setattr(YouTubeClient, "get", lambda: service)
    return service


@pytest.mark.parametrize(("reference", "selector"), [
    (CHANNEL_ID, {"id": CHANNEL_ID}),
    ("  " + CHANNEL_ID + "  ", {"id": CHANNEL_ID}),
    ("UC" + "A0_-" * 5 + "Z9", {"id": "UC" + "A0_-" * 5 + "Z9"}),
    (HANDLE, {"forHandle": HANDLE}),
    ("@abc", {"forHandle": "@abc"}),
    ("@" + "a" * 30, {"forHandle": "@" + "a" * 30}),
    ("https://youtube.com/channel/" + CHANNEL_ID, {"id": CHANNEL_ID}),
    ("https://www.youtube.com/channel/" + CHANNEL_ID + "/", {"id": CHANNEL_ID}),
    ("https://m.youtube.com/" + HANDLE, {"forHandle": HANDLE}),
    ("https://www.youtube.com:443/" + HANDLE, {"forHandle": HANDLE}),
    ("https://www.youtube.com/%40owned.channel", {"forHandle": HANDLE}),
])
def test_channel_selector_accepts_explicit_canonical_identities(reference, selector):
    assert channel_selector(reference) == selector


@pytest.mark.parametrize("reference", [
    "", "UC" + "a" * 21, "UC" + "a" * 23, "Uc" + "a" * 22,
    "UC" + "a" * 21 + "!", "@ab", "@" + "a" * 31, "@owned channel",
    "@owned/channel", "ownedchannel", "http://youtube.com/" + HANDLE,
    "ftp://youtube.com/" + HANDLE, "https://youtube.com.evil.invalid/" + HANDLE,
    "https://evil-youtube.com/" + HANDLE, "https://yоutube.com/" + HANDLE,
    "https://youtube.com@evil.invalid/" + HANDLE,
    "https://user@youtube.com/" + HANDLE,
    "https://user:password@youtube.com/channel/" + CHANNEL_ID,
    "https://www.youtube.com:444/" + HANDLE,
    "https://www.youtube.com:notaport/" + HANDLE,
    "https://youtu.be/" + HANDLE, "https://youtube.com/c/ownedchannel",
    "https://youtube.com/user/ownedchannel", "https://youtube.com/watch?v=" + VIDEO_ID,
    "https://youtube.com/channel/" + CHANNEL_ID + "/videos",
    "https://youtube.com/@owned%2Fchannel",
])
def test_channel_selector_rejects_ambiguous_or_credentialed_references(reference):
    with pytest.raises(ValueError):
        channel_selector(reference)


def test_installed_google_discovery_supports_for_handle_without_requests():
    """GIVEN installed discovery WHEN channels.list is constructed THEN forHandle is real."""
    document = Path(discovery_cache.__file__).parent / "documents/youtube.v3.json"
    schema = json.loads(document.read_text())
    parameter = schema["resources"]["channels"]["methods"]["list"]["parameters"]["forHandle"]
    assert parameter["type"] == "string" and parameter["location"] == "query"
    http = MagicMock()
    http.credentials = None
    http.request.side_effect = AssertionError("Discovery must not make requests")
    api = build("youtube", "v3", developerKey="owned-discovery-key", http=http,
                static_discovery=True, cache_discovery=False)
    request = api.channels().list(part="snippet", forHandle=HANDLE, maxResults=1)
    assert parse_qs(urlparse(request.uri).query)["forHandle"] == [HANDLE]
    assert request.method == "GET"
    http.request.assert_not_called()


@pytest.mark.parametrize("reference", [CHANNEL_ID, HANDLE, "https://youtube.com/" + HANDLE])
async def test_channel_metadata_identity_counts_and_unknown_source_bytes(reference, service):
    """GIVEN one API response WHEN inspected THEN provider facts stay distinct from bytes."""
    result = await channel_metadata(reference)
    assert result["channel_id"] == CHANNEL_ID
    assert result["title"] == "Owned fixture channel" and result["country"] == "NL"
    assert result["subscriber_count"] == 17 and result["view_count"] == 456
    assert result["video_count"] == 123 and result["uploads_playlist_id"] == PLAYLIST_ID
    assert result["provenance"] == {
        "provider": "youtube-data-api-v3", "operation": "channels.list",
        "media_downloaded": False, "source_bytes_state": "unknown",
    }
    service.channels.return_value.list.assert_called_once_with(
        part="snippet,statistics,contentDetails", maxResults=1, **channel_selector(reference)
    )
    service.channels.return_value.list.return_value.execute.assert_called_once_with(num_retries=0)
    service.playlistItems.assert_not_called()


async def test_hidden_subscriber_counts_are_absent_instead_of_invented(service):
    response = channel_response()
    response["items"][0]["statistics"] = {"hiddenSubscriberCount": True}
    service.channels.return_value.list.return_value.execute.return_value = response
    result = await channel_metadata(HANDLE)
    assert result["hidden_subscriber_count"] is True
    assert all(result[name] is None for name in ["subscriber_count", "video_count", "view_count"])


@pytest.mark.parametrize("response", [{}, {"items": []}])
async def test_channel_metadata_missing_is_an_actionable_tool_error(response, service):
    service.channels.return_value.list.return_value.execute.return_value = response
    result = await youtube_channel_inspect(HANDLE)
    assert "not found or unavailable" in result["error"]
    assert {"category", "hint", "retryable"} <= result.keys()
    assert result["retryable"] is False and "channel_id" not in result


@pytest.mark.parametrize("returned_id", [OTHER_CHANNEL_ID, "UCbad", "not-a-channel"])
async def test_channel_metadata_rejects_changed_or_malformed_response_identity(returned_id, service):
    response = channel_response()
    response["items"][0]["id"] = returned_id
    service.channels.return_value.list.return_value.execute.return_value = response
    result = await youtube_channel_inspect(CHANNEL_ID)
    assert "identity does not match" in result["error"]
    assert "channel_id" not in result


@pytest.mark.parametrize("tool", [youtube_channel_inspect, youtube_channel_catalog])
async def test_channel_permission_failure_uses_existing_403_hint(tool, service):
    service.channels.return_value.list.return_value.execute.side_effect = HttpError(
        Response({"status": "403"}),
        b'{"error":{"message":"Permission denied","code":403}}',
        uri="https://youtube.googleapis.com/youtube/v3/channels",
    )
    result = await tool(HANDLE)
    assert result["category"] == "API_PERMISSION_DENIED" and result["retryable"] is False
    assert "YouTube Data API v3" in result["hint"] and "YOUTUBE_API_KEY" in result["hint"]
    assert "channel_id" not in result and "items" not in result
    service.channels.return_value.list.return_value.execute.assert_called_once_with(num_retries=0)
    service.playlistItems.assert_not_called()


async def test_catalog_is_one_page_and_retains_requested_and_returned_tokens(service):
    """GIVEN more reported uploads WHEN cataloged THEN only this page is covered."""
    result = await channel_catalog(HANDLE, 2, "prior-owned-page")
    assert result["channel"]["channel_id"] == CHANNEL_ID
    assert result["returned_items"] == 2 and result["playlist_reported_total"] == 123
    assert result["coverage"] == "one_api_page" and result["next_page_token"] == "next-owned-page"
    assert result["items"][0] == {
        "video_id": VIDEO_ID, "title": "Owned video 0", "position": 0,
        "published_at": "2026-01-02T00:00:00Z",
        "url": "https://www.youtube.com/watch?v=" + VIDEO_ID,
    }
    assert result["provenance"]["media_downloaded"] is False
    assert result["provenance"]["source_bytes_state"] == "unknown"
    service.playlistItems.return_value.list.assert_called_once_with(
        part="snippet", playlistId=PLAYLIST_ID, maxResults=2, pageToken="prior-owned-page"
    )
    service.playlistItems.return_value.list.return_value.execute.assert_called_once_with(num_retries=0)
    service.playlistItems.return_value.list_next.assert_not_called()


async def test_catalog_caps_returned_entries_at_fifty_without_following_next_page(service):
    service.playlistItems.return_value.list.return_value.execute.return_value = catalog_response(51)
    result = await youtube_channel_catalog(CHANNEL_ID, 50)
    assert result["returned_items"] == len(result["items"]) == 50
    assert result["next_page_token"] == "next-owned-page"
    service.playlistItems.return_value.list.assert_called_once_with(
        part="snippet", playlistId=PLAYLIST_ID, maxResults=50
    )
    service.playlistItems.return_value.list_next.assert_not_called()


@pytest.mark.parametrize("content_details", [{}, {"relatedPlaylists": {}}, {"relatedPlaylists": {"uploads": None}}])
async def test_catalog_missing_uploads_stops_before_playlist_query(content_details, service):
    response = channel_response()
    response["items"][0]["contentDetails"] = deepcopy(content_details)
    service.channels.return_value.list.return_value.execute.return_value = response
    result = await youtube_channel_catalog(HANDLE)
    assert "uploads playlist is unavailable" in result["error"]
    assert "items" not in result
    service.playlistItems.assert_not_called()


@pytest.mark.parametrize("playlist_id", ["../other", "https://example.invalid/list", "a" * 129])
async def test_catalog_rejects_unbound_playlist_identity_before_query(playlist_id, service):
    response = channel_response()
    response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"] = playlist_id
    service.channels.return_value.list.return_value.execute.return_value = response
    result = await youtube_channel_catalog(HANDLE)
    assert "Invalid channel uploads playlist identity" in result["error"]
    service.playlistItems.assert_not_called()


@pytest.mark.parametrize("max_items", [0, 51])
async def test_direct_catalog_bounds_stop_before_provider_access(max_items, service):
    result = await youtube_channel_catalog(HANDLE, max_items)
    assert "between 1 and 50" in result["error"]
    service.channels.assert_not_called()
    service.playlistItems.assert_not_called()


async def test_actual_mcp_registration_parameter_validation_and_structured_errors(service):
    """GIVEN mounted tools WHEN called through FastMCP THEN schema and errors are observable."""
    from video_research_mcp.server import app

    async with Client(app) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        for name in ["youtube_channel_inspect", "youtube_channel_catalog"]:
            tool = tools[name]
            assert tool.annotations.read_only_hint is True
            assert tool.annotations.idempotent_hint is True
            assert tool.annotations.open_world_hint is True
            assert tool.annotations.destructive_hint is False
            assert tool.input_schema["required"] == ["reference"]
        catalog = tools["youtube_channel_catalog"]
        assert catalog.input_schema["properties"]["max_items"]["maximum"] == 50
        for arguments in [
            {"reference": HANDLE, "max_items": 51},
            {"reference": HANDLE, "max_items": 0},
            {"reference": HANDLE, "page_token": "a" * 1025},
            {},
        ]:
            result = await client.call_tool("youtube_channel_catalog", arguments, raise_on_error=False)
            assert result.is_error
        service.channels.assert_not_called()
        invalid = await client.call_tool("youtube_channel_inspect", {"reference": "https://user:pass@youtube.com/" + HANDLE})
        validate(invalid.structured_content, tools["youtube_channel_inspect"].output_schema)
        assert "error" in invalid.structured_content and not invalid.is_error
        service.channels.assert_not_called()
        metadata = await client.call_tool("youtube_channel_inspect", {"reference": HANDLE})
        validate(metadata.structured_content, tools["youtube_channel_inspect"].output_schema)
        assert metadata.structured_content["channel_id"] == CHANNEL_ID


async def test_actual_mcp_channel_catalog_to_existing_video_metadata_flow(service, monkeypatch):
    """GIVEN an inspected channel WHEN catalog URL is reused THEN existing metadata binds that video."""
    from video_research_mcp.tools.youtube import youtube_server

    response = {"items": [{
        "snippet": {"title": "Owned video", "channelId": CHANNEL_ID,
                    "channelTitle": "Owned fixture channel", "categoryId": "27"},
        "contentDetails": {"duration": "PT12S"}, "statistics": {"viewCount": "7"},
    }]}
    service.videos.return_value.list.return_value.execute.return_value = response
    storage = AsyncMock()
    monkeypatch.setattr("video_research_mcp.weaviate_store.store_video_metadata", storage)
    async with Client(youtube_server) as client:
        inspected = (await client.call_tool("youtube_channel_inspect", {"reference": HANDLE})).structured_content
        catalog = (await client.call_tool("youtube_channel_catalog", {"reference": inspected["channel_id"], "max_items": 1})).structured_content
        video = (await client.call_tool("video_metadata", {"url": catalog["items"][0]["url"]})).structured_content
    assert inspected["channel_id"] == catalog["channel"]["channel_id"] == video["channel_id"]
    assert video["video_id"] == catalog["items"][0]["video_id"] == VIDEO_ID
    assert video["duration_seconds"] == 12 and video["view_count"] == 7
    service.videos.return_value.list.assert_called_once_with(
        part="snippet,contentDetails,statistics", id=VIDEO_ID
    )
    storage.assert_awaited_once_with(video)
