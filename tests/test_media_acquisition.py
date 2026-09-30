"""Bounded acquisition and public MCP routes using original transport fixtures."""

import hashlib
import asyncio
import json
import threading
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client

from video_research_mcp import media_acquisition as acquisition
from video_research_mcp.media_assets import AssetCatalog
from video_research_mcp.tools.media_assets import media_assets_server
from video_research_mcp.url_policy import UrlPolicyError

LOOM = "https://www.loom.com/share/0123456789abcdef0123456789abcdef"
DIRECT = "https://cdn.example.invalid/original.mp4?token=opaque-fixture-token"
OWNED = b"Original rights-owned media bytes"


@pytest.fixture(autouse=True)
def isolated_acquisition(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    monkeypatch.setenv("MEDIA_COOKIES_FILE", "")


def fixture_fetch(body=OWNED, content_type="video/mp4", final_url=DIRECT):
    async def fetch(url, directory, *, max_bytes, allowed_content_types=None):
        if len(body) > max_bytes:
            raise UrlPolicyError("Response exceeds size limit")
        if allowed_content_types and content_type not in allowed_content_types:
            raise UrlPolicyError("Response content type is not allowed")
        path = directory / "fixture.bin"
        path.write_bytes(body)
        return {
            "path": path,
            "final_url": final_url,
            "content_type": content_type,
            "content_length": len(body),
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }

    return AsyncMock(side_effect=fetch)


async def test_direct_metadata_is_head_only_zero_video_download():
    """GIVEN a direct video WHEN metadata is requested THEN HEAD never starts acquisition or inference."""
    with (
        patch.object(
            acquisition,
            "head_resource",
            AsyncMock(
                return_value={
                    "final_url": DIRECT,
                    "content_type": "video/mp4",
                    "content_length": len(OWNED),
                }
            ),
        ) as head,
        patch.object(acquisition, "fetch_resource", side_effect=AssertionError("no GET")),
        patch(
            "video_research_mcp.client.GeminiClient.get", side_effect=AssertionError("no provider")
        ),
    ):
        result = await acquisition.source_metadata(DIRECT)
    head.assert_awaited_once_with(DIRECT)
    assert result["media_download_bytes"] == 0
    assert "opaque-fixture-token" not in json.dumps(result)


async def test_loom_metadata_get_is_guarded_and_resolves_without_video_download():
    body = json.dumps(
        {"@type": "VideoObject", "name": "Owned fixture", "contentUrl": DIRECT}
    ).encode()
    fetch = fixture_fetch(body, "application/json", LOOM)
    with patch.object(acquisition, "fetch_resource", fetch):
        result = await acquisition.source_metadata(LOOM)
    assert fetch.await_count == 1
    assert fetch.call_args.kwargs["allowed_content_types"] == (
        "text/html",
        "application/json",
        "application/ld+json",
    )
    assert fetch.call_args.kwargs["max_bytes"] == 1024 * 1024
    assert result["media_download_bytes"] == 0
    assert result["metadata"]["page_sha256"] == hashlib.sha256(body).hexdigest()
    assert result["metadata"]["live_verified"] is False
    assert "opaque-fixture-token" not in json.dumps(result)


async def test_loom_media_body_mislabel_is_rejected_by_header_guard():
    with patch.object(acquisition, "fetch_resource", fixture_fetch(OWNED, "video/mp4", LOOM)):
        with pytest.raises(UrlPolicyError, match="content type"):
            await acquisition.source_metadata(LOOM)


async def test_local_metadata_uses_bounded_probe_and_exact_revision(tmp_path):
    source = tmp_path / "owned.mp4"
    source.write_bytes(OWNED)
    stdout = (
        b'{"format":{"duration":"3.0"},"streams":[{"codec_type":"video","width":16,"height":16}]}'
    )
    with (
        patch.object(acquisition.shutil, "which", return_value="/owned/ffprobe"),
        patch.object(
            acquisition, "run_media_process", AsyncMock(return_value=(stdout, b""))
        ) as process,
        patch.object(acquisition, "fetch_resource", side_effect=AssertionError("no fetch")),
    ):
        result = await acquisition.source_metadata(str(source))
    command, timeout = process.call_args.args
    assert command[command.index("-protocol_whitelist") + 1] == "file"
    assert command[-1] != str(source) and Path(command[-1]).suffix == ".mp4" and timeout == 120
    assert result["metadata"]["sha256"] == hashlib.sha256(OWNED).hexdigest()
    assert (
        result["media_download_bytes"] == 0
        and result["metadata"]["probe"]["streams"][0]["width"] == 16
    )


async def test_missing_ffprobe_is_actionable_and_does_not_download(tmp_path):
    source = tmp_path / "owned.mp4"
    source.write_bytes(OWNED)
    with patch.object(acquisition.shutil, "which", return_value=None):
        with pytest.raises(RuntimeError, match="ffprobe not found"):
            await acquisition.source_metadata(str(source))


async def test_local_acquisition_copies_bytes_restart_dedups_and_removes_only_owned(tmp_path):
    """GIVEN a local source WHEN acquired, reopened and removed THEN exact bytes survive in the original."""
    source = tmp_path / "original.mp4"
    source.write_bytes(OWNED)
    first = await acquisition.acquire_media(str(source))
    second = await acquisition.acquire_media(str(source))
    assert first["asset_id"] == second["asset_id"] == hashlib.sha256(OWNED).hexdigest()
    assert first["reused"] is False and second["reused"] is True
    assert first["path"] != str(source) and Path(first["path"]).read_bytes() == OWNED
    assert first["source_kind"] == "local"
    AssetCatalog().remove(first["asset_id"])
    assert source.read_bytes() == OWNED and AssetCatalog().list()["total"] == 0


async def test_direct_acquisition_has_checked_byte_provenance_and_no_optional_downloader():
    with (
        patch.object(acquisition, "fetch_resource", fixture_fetch()) as fetch,
        patch(
            "video_research_mcp.tools.youtube_download.download_youtube_video",
            side_effect=AssertionError("YouTube only"),
        ),
        patch.object(
            acquisition, "run_media_process", side_effect=AssertionError("no remote process")
        ),
    ):
        result = await acquisition.acquire_media(DIRECT)
    assert Path(result["path"]).read_bytes() == OWNED
    assert result["asset_id"] == result["provenance"][0]["acquisition"]["transport"]["sha256"]
    assert fetch.await_count == 1 and fetch.call_args.kwargs["max_bytes"] == 512 * 1024 * 1024
    assert "opaque-fixture-token" not in json.dumps(result)
    assert result["inference_performed"] is result["upload_performed"] is False


async def test_loom_explicit_page_resolution_downloads_actual_fixture_video():
    """GIVEN a fixture page and video WHEN acquired THEN the resolved checked route commits video bytes."""
    page = json.dumps({"@type": "VideoObject", "contentUrl": DIRECT}).encode()
    metadata_fetch = fixture_fetch(page, "application/json", LOOM)
    media_fetch = fixture_fetch()

    async def fetch(url, directory, **kwargs):
        return await (metadata_fetch if url == LOOM else media_fetch)(url, directory, **kwargs)

    with patch.object(acquisition, "fetch_resource", AsyncMock(side_effect=fetch)):
        result = await acquisition.acquire_media(LOOM)
    assert metadata_fetch.await_count == media_fetch.await_count == 1
    media_fetch.assert_awaited_once()
    assert media_fetch.call_args.args[0] == DIRECT
    assert Path(result["path"]).read_bytes() == OWNED
    assert result["source_kind"] == "loom"
    assert result["provenance"][0]["acquisition"]["live_verified"] is False


async def test_unsupported_loom_page_never_fetches_video_and_cleans_staging():
    with patch.object(
        acquisition,
        "fetch_resource",
        fixture_fetch(b"<html>Login required</html>", "text/html", LOOM),
    ) as fetch:
        with pytest.raises(ValueError, match="authentication"):
            await acquisition.acquire_media(LOOM)
    assert fetch.await_count == 1
    catalog = AssetCatalog()
    assert catalog.list()["total"] == 0 and list(catalog.staging.iterdir()) == []


async def test_youtube_id_only_dispatch_retains_shared_bounded_downloader_contract():
    async def download(video_id, directory):
        assert video_id == "Abcdefgh_12"
        path = directory / (video_id + ".mp4")
        path.write_bytes(OWNED)
        path.with_suffix(".receipt.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "video_id": video_id,
                    "bytes": len(OWNED),
                    "sha256": hashlib.sha256(OWNED).hexdigest(),
                }
            )
        )
        return path

    with patch(
        "video_research_mcp.tools.youtube_download.download_youtube_video",
        AsyncMock(side_effect=download),
    ) as downloader:
        result = await acquisition.acquire_media("https://youtube.com/watch?v=Abcdefgh_12")
    assert downloader.await_count == 1 and result["source_kind"] == "youtube"
    assert result["provenance"][0]["acquisition"]["method"] == "youtube_id_only_yt_dlp"


@pytest.mark.parametrize(
    "message",
    [
        "yt-dlp not found; install independently",
        "MEDIA_COOKIES_FILE is unavailable",
        "yt-dlp failed; check configured cookies",
    ],
)
async def test_youtube_dependency_and_cookie_errors_retain_actionable_result(message):
    from video_research_mcp.tools.media_assets import media_acquire

    with patch(
        "video_research_mcp.tools.youtube_download.download_youtube_video",
        AsyncMock(side_effect=RuntimeError(message)),
    ):
        result = await media_acquire("https://youtube.com/watch?v=Abcdefgh_12")
    assert message in result["error"]
    assert AssetCatalog().list()["total"] == 0 and list(AssetCatalog().staging.iterdir()) == []


async def test_outside_local_root_and_symlink_never_acquire(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path / "allowed"))
    original = tmp_path / "original.mp4"
    original.write_bytes(OWNED)
    symlink = tmp_path / "symlink.mp4"
    symlink.symlink_to(original)
    for source in (original, symlink):
        with pytest.raises(PermissionError):
            await acquisition.acquire_media(str(source))
    assert original.read_bytes() == OWNED and AssetCatalog().list()["total"] == 0


async def test_bad_transport_digest_fails_without_partial_assets():
    good_fetch = fixture_fetch()

    async def altered(url, directory, **kwargs):
        result = await good_fetch(url, directory, **kwargs)
        result["sha256"] = "a" * 64
        return result

    with patch.object(acquisition, "fetch_resource", AsyncMock(side_effect=altered)):
        with pytest.raises(ValueError, match="transport receipt"):
            await acquisition.acquire_media(DIRECT)
    assert AssetCatalog().list()["total"] == 0 and list(AssetCatalog().staging.iterdir()) == []


async def test_helper_outside_staging_never_moves_or_reads_original(tmp_path):
    original = tmp_path / "original.mp4"
    original.write_bytes(OWNED)
    fetched = {
        "path": original,
        "final_url": DIRECT,
        "content_type": "video/mp4",
        "bytes": len(OWNED),
        "sha256": hashlib.sha256(OWNED).hexdigest(),
    }
    with patch.object(acquisition, "fetch_resource", AsyncMock(return_value=fetched)):
        with pytest.raises(PermissionError, match="owned regular staging"):
            await acquisition.acquire_media(DIRECT)
    assert original.read_bytes() == OWNED and AssetCatalog().list()["total"] == 0


async def test_hls_nested_owned_output_is_adopted_with_exact_remux_receipt():
    async def hls(url, staging):
        nested = staging / "hls-owned"
        nested.mkdir()
        path = nested / "acquired.mp4"
        path.write_bytes(OWNED)
        return {
            "path": path,
            "provenance": {
                "output": {"sha256": hashlib.sha256(OWNED).hexdigest(), "bytes": len(OWNED)},
                "ffmpeg_network": "disabled",
                "container_probe": {"streams": [{"codec_type": "video"}]},
            },
        }

    with patch("video_research_mcp.media_hls.acquire_hls", AsyncMock(side_effect=hls)) as helper:
        result = await acquisition.acquire_media("https://cdn.example.invalid/owned.m3u8")
    assert helper.await_count == 1 and Path(result["path"]).read_bytes() == OWNED
    assert result["media_probe_performed"] is True
    assert result["provenance"][0]["acquisition"]["transport"]["ffmpeg_network"] == "disabled"


async def test_cancel_joins_real_copy_worker_before_staging_cleanup(tmp_path):
    """GIVEN an admitted copy thread WHEN canceled THEN it exits before owned staging disappears."""
    source = tmp_path / "original.mp4"
    source.write_bytes(OWNED)
    admitted, exited = threading.Event(), threading.Event()

    def controlled(catalog, path, **kwargs):
        admitted.set()
        assert kwargs["cancelled"].wait(5)
        assert catalog.staging.exists()
        exited.set()
        raise TimeoutError("controlled copy canceled")

    with patch.object(AssetCatalog, "adopt", controlled):
        task = asyncio.create_task(acquisition.acquire_media(str(source)))
        assert await asyncio.to_thread(admitted.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert exited.is_set()
    assert source.read_bytes() == OWNED
    assert list(AssetCatalog().staging.iterdir()) == [] and AssetCatalog().list()["total"] == 0


async def test_actual_mcp_discovery_and_owned_asset_journey(tmp_path):
    """GIVEN actual FastMCP calls WHEN acquired/listed/removed THEN schema and owned lifecycle agree."""
    source = tmp_path / "owned.mp4"
    source.write_bytes(OWNED)
    async with Client(media_assets_server) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == {
            "media_source_inspect",
            "media_metadata",
            "media_acquire",
            "media_assets_list",
            "media_asset_remove",
        }
        acquired = (
            await client.call_tool("media_acquire", {"source": str(source)})
        ).structured_content
        assets = (await client.call_tool("media_assets_list", {})).structured_content
        assert assets["assets"][0]["asset_id"] == acquired["asset_id"]
        removed = (
            await client.call_tool("media_asset_remove", {"asset_id": acquired["asset_id"]})
        ).structured_content
        assert removed["removed"] is True
        bad = await client.call_tool(
            "media_asset_remove", {"asset_id": str(source)}, raise_on_error=False
        )
        assert bad.is_error
    assert source.read_bytes() == OWNED and AssetCatalog().list()["total"] == 0
