"""Tests for the context cache bridge — video_analyze → sessions → generate_content."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import video_research_mcp.config as cfg_mod
import video_research_mcp.context_cache as cc_mod
from video_research_mcp.sessions import SessionStore
from video_research_mcp.tools.video import (
    video_analyze,
    video_create_session,
    video_continue_session,
)

TEST_URL = "https://www.youtube.com/watch?v=GcNu6wrLTJc"
TEST_VIDEO_ID = "GcNu6wrLTJc"
TEST_CACHE_NAME = "cachedContents/test-bridge-123"


async def _passthrough_retry(fn):
    """Mock with_retry that just awaits the coroutine factory."""
    return await fn()


@pytest.fixture(autouse=True)
def _clean_config(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    cfg_mod._config = None
    yield
    cfg_mod._config = None


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Ensure cache registry is empty and _loaded reset between tests."""
    cc_mod._registry.clear()
    cc_mod._pending.clear()
    cc_mod._suppressed.clear()
    cc_mod._last_failure.clear()
    cc_mod._loaded = True
    yield
    cc_mod._registry.clear()
    cc_mod._pending.clear()
    cc_mod._suppressed.clear()
    cc_mod._last_failure.clear()
    cc_mod._loaded = True


@pytest.fixture(autouse=True)
def _isolate_registry_path(tmp_path):
    """Redirect registry persistence to temp dir — never touch real filesystem."""
    json_path = tmp_path / "context_cache_registry.json"
    with patch.object(cc_mod, "_registry_path", return_value=json_path):
        yield json_path


@pytest.fixture()
def _mock_session_store():
    """Provide an isolated in-memory session store."""
    store = SessionStore()
    with patch("video_research_mcp.tools.video.session_store", store):
        yield store


FILE_API_URI = "https://generativelanguage.googleapis.com/v1beta/files/abc123"


class TestEnsureSessionCache:
    """Verify ensure_session_cache lookup → on-demand creation fallback.

    Uses a File API URI (not YouTube URL) because ensure_session_cache now
    skips YouTube URLs — they can't be cached via caches.create().
    """

    async def test_skips_youtube_urls(self):
        """GIVEN a YouTube URL WHEN ensure_session_cache called THEN returns empty with reason."""
        from video_research_mcp.tools.video_cache import ensure_session_cache

        cache_name, model, reason = await ensure_session_cache(TEST_VIDEO_ID, TEST_URL)

        assert cache_name == ""
        assert model == ""
        assert reason == "skipped:youtube_url"

    async def test_returns_existing_cache_from_registry(self):
        """GIVEN a registry entry WHEN ensure_session_cache called THEN returns it."""
        from video_research_mcp.tools.video_cache import ensure_session_cache

        cfg = cfg_mod.get_config()
        cc_mod._registry[(TEST_VIDEO_ID, cfg.default_model)] = TEST_CACHE_NAME

        cache_name, model, reason = await ensure_session_cache(TEST_VIDEO_ID, FILE_API_URI)

        assert cache_name == TEST_CACHE_NAME
        assert model == cfg.default_model
        assert reason == ""

    async def test_creates_cache_on_demand_when_registry_empty(self):
        """GIVEN empty registry WHEN ensure_session_cache called THEN creates via get_or_create."""
        from video_research_mcp.tools.video_cache import ensure_session_cache

        mock_cached = MagicMock()
        mock_cached.name = "cachedContents/on-demand-456"

        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(return_value=mock_cached)

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            cache_name, model, reason = await ensure_session_cache(TEST_VIDEO_ID, FILE_API_URI)

        assert cache_name == "cachedContents/on-demand-456"
        cfg = cfg_mod.get_config()
        assert model == cfg.default_model
        assert reason == ""

    async def test_returns_empty_with_reason_when_both_fail(self):
        """GIVEN empty registry AND create fails WHEN called THEN returns empty + reason."""
        from video_research_mcp.tools.video_cache import ensure_session_cache

        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(side_effect=Exception("API error"))

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            cache_name, model, reason = await ensure_session_cache(TEST_VIDEO_ID, FILE_API_URI)

        assert cache_name == ""
        assert model == ""
        assert "api_error" in reason

    async def test_skips_create_when_suppressed_with_reason(self):
        """GIVEN suppressed video WHEN ensure_session_cache called THEN returns suppression reason."""
        from video_research_mcp.tools.video_cache import ensure_session_cache

        cfg = cfg_mod.get_config()
        cc_mod._suppressed.add((TEST_VIDEO_ID, cfg.default_model))

        with patch("video_research_mcp.context_cache.GeminiClient.get") as mock_get:
            cache_name, model, reason = await ensure_session_cache(TEST_VIDEO_ID, FILE_API_URI)

        assert cache_name == ""
        assert reason == "suppressed:too_few_tokens"
        mock_get.assert_not_called()

    async def test_returns_timeout_reason(self):
        """GIVEN slow cache creation WHEN timeout exceeded THEN returns timeout reason."""
        import asyncio
        from video_research_mcp.tools.video_cache import ensure_session_cache

        real_wait_for = asyncio.wait_for

        async def fake_wait_for(coro, timeout=None):
            """Immediately timeout for the 60s wait, pass through others."""
            if timeout == 60.0:
                raise asyncio.TimeoutError()
            return await real_wait_for(coro, timeout=timeout)

        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(return_value=MagicMock(name="cachedContents/never"))

        with (
            patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client),
            patch("video_research_mcp.tools.video_cache.asyncio.wait_for", side_effect=fake_wait_for),
        ):
            cache_name, model, reason = await ensure_session_cache(TEST_VIDEO_ID, FILE_API_URI)

        assert cache_name == ""
        assert reason == "timeout:60s"

    async def test_deduplicates_against_pending_prewarm_after_timeout(self):
        """GIVEN a slow prewarm that outlasts lookup_or_await's timeout
        WHEN ensure_session_cache falls to slow path THEN joins the pending
        task via start_prewarm instead of creating a duplicate cache."""
        import asyncio
        from video_research_mcp.tools.video_cache import ensure_session_cache

        mock_cached = MagicMock()
        mock_cached.name = "cachedContents/dedup-789"

        create_count = 0

        async def slow_create(*args, **kwargs):
            nonlocal create_count
            create_count += 1
            await asyncio.sleep(0.2)
            return mock_cached

        mock_client = MagicMock()
        mock_client.aio.caches.create = slow_create

        # Capture the REAL lookup_or_await before patching
        real_lookup_or_await = cc_mod.lookup_or_await

        async def short_timeout_lookup(content_id, model, timeout=5.0):
            """Delegate to real function with a very short timeout."""
            return await real_lookup_or_await(content_id, model, timeout=0.05)

        with (
            patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client),
            patch.object(cc_mod, "lookup_or_await", side_effect=short_timeout_lookup),
        ):
            # Start a slow prewarm (as if video_analyze just fired it)
            from google.genai import types as gtypes
            warm_parts = [gtypes.Part(file_data=gtypes.FileData(file_uri=FILE_API_URI))]
            cfg = cfg_mod.get_config()
            cc_mod.start_prewarm(TEST_VIDEO_ID, warm_parts, cfg.default_model)

            # ensure_session_cache: resolve_session_cache times out → slow path
            # slow path calls start_prewarm → returns same task (dedup)
            cache_name, model, _reason = await ensure_session_cache(TEST_VIDEO_ID, FILE_API_URI)

        assert cache_name == "cachedContents/dedup-789"
        # Only ONE create call — the slow path joined the pending task
        assert create_count == 1


class TestVideoAnalyzePrewarm:
    async def test_video_analyze_skips_prewarm_for_youtube(self, mock_gemini_client):
        """GIVEN a YouTube URL WHEN video_analyze completes THEN skips prewarm.

        YouTube URLs can't be cached via caches.create() (400 INVALID_ARGUMENT),
        so prewarm_cache returns early without calling start_prewarm.
        """
        from video_research_mcp.models.video import VideoResult

        mock_gemini_client["generate_structured"].return_value = VideoResult(
            title="Test", summary="Summary", key_points=["point"]
        )

        with patch.object(cc_mod, "start_prewarm", return_value=MagicMock()) as mock_prewarm:
            result = await video_analyze(url=TEST_URL, use_cache=False)

        assert "error" not in result
        mock_prewarm.assert_not_called()


class TestCreateSessionCache:
    async def test_youtube_without_download_returns_uncached(
        self, mock_gemini_client, _mock_session_store
    ):
        """GIVEN YouTube URL without download WHEN video_create_session called THEN uncached.

        YouTube URLs can't be cached via caches.create(), so we skip the attempt
        entirely when download=False (default).
        """
        mock_gemini_client["generate"].return_value = "Test Title"

        result = await video_create_session(url=TEST_URL)

        assert result["cache_status"] == "uncached"
        assert result["download_status"] == ""
        assert result["local_filepath"] == ""
        session = _mock_session_store.get(result["session_id"])
        assert session.cache_name == ""

    async def test_download_true_creates_cached_session(
        self, mock_gemini_client, _mock_session_store
    ):
        """GIVEN download=True WHEN video_create_session called THEN downloads, uploads, caches."""
        from pathlib import Path

        mock_gemini_client["generate"].return_value = "Test Title"

        mock_cached = MagicMock()
        mock_cached.name = TEST_CACHE_NAME

        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(return_value=mock_cached)

        with (
            patch(
                "video_research_mcp.tools.video.download_youtube_video",
                new_callable=AsyncMock,
                return_value=Path("/tmp/test.mp4"),
            ),
            patch(
                "video_research_mcp.tools.video._upload_large_file",
                new_callable=AsyncMock,
                return_value=FILE_API_URI,
            ),
            patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client),
        ):
            result = await video_create_session(url=TEST_URL, download=True)

        assert result["cache_status"] == "cached"
        assert result["download_status"] == "downloaded"
        assert result["local_filepath"] == "/tmp/test.mp4"
        session = _mock_session_store.get(result["session_id"])
        assert session.cache_name == TEST_CACHE_NAME
        # Session URL should be the File API URI, not the YouTube URL
        assert session.url == FILE_API_URI

    async def test_download_true_falls_back_when_ytdlp_missing(
        self, mock_gemini_client, _mock_session_store
    ):
        """GIVEN yt-dlp not installed WHEN download=True THEN returns unavailable status."""
        mock_gemini_client["generate"].return_value = "Test Title"

        with patch(
            "video_research_mcp.tools.video.download_youtube_video",
            new_callable=AsyncMock,
            side_effect=RuntimeError("yt-dlp not found"),
        ):
            result = await video_create_session(url=TEST_URL, download=True)

        assert result["cache_status"] == "uncached"
        assert result["download_status"] == "unavailable"

    async def test_download_true_upload_fails_gracefully(
        self, mock_gemini_client, _mock_session_store
    ):
        """GIVEN download succeeds but upload fails WHEN download=True THEN fails gracefully."""
        from pathlib import Path

        mock_gemini_client["generate"].return_value = "Test Title"

        with (
            patch(
                "video_research_mcp.tools.video.download_youtube_video",
                new_callable=AsyncMock,
                return_value=Path("/tmp/test.mp4"),
            ),
            patch(
                "video_research_mcp.tools.video._upload_large_file",
                new_callable=AsyncMock,
                side_effect=Exception("Upload failed"),
            ),
        ):
            result = await video_create_session(url=TEST_URL, download=True)

        assert result["cache_status"] == "uncached"
        assert result["download_status"] == "failed"
        assert result["local_filepath"] == "/tmp/test.mp4"

    async def test_download_true_cache_fails_but_upload_succeeds(
        self, mock_gemini_client, _mock_session_store
    ):
        """GIVEN download+upload succeed but cache creation fails THEN session uses File API URI uncached."""
        from pathlib import Path

        mock_gemini_client["generate"].return_value = "Test Title"

        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(side_effect=Exception("Cache error"))

        with (
            patch(
                "video_research_mcp.tools.video.download_youtube_video",
                new_callable=AsyncMock,
                return_value=Path("/tmp/test.mp4"),
            ),
            patch(
                "video_research_mcp.tools.video._upload_large_file",
                new_callable=AsyncMock,
                return_value=FILE_API_URI,
            ),
            patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client),
        ):
            result = await video_create_session(url=TEST_URL, download=True)

        # Cache failed but download+upload succeeded — still uses File API URI
        assert result["cache_status"] == "uncached"
        assert result["download_status"] == "downloaded"
        assert result["local_filepath"] == "/tmp/test.mp4"
        session = _mock_session_store.get(result["session_id"])
        # Session should use File API URI even without cache
        assert session.url == FILE_API_URI

    async def test_download_true_handles_non_runtime_error(
        self, mock_gemini_client, _mock_session_store
    ):
        """GIVEN download raises OSError WHEN download=True THEN degrades gracefully."""
        mock_gemini_client["generate"].return_value = "Test Title"

        with patch(
            "video_research_mcp.tools.video.download_youtube_video",
            new_callable=AsyncMock,
            side_effect=OSError("Permission denied"),
        ):
            result = await video_create_session(url=TEST_URL, download=True)

        assert result["cache_status"] == "uncached"
        assert result["download_status"] == "failed"
        assert "error" not in result

class TestContinueSessionCache:
    @pytest.fixture()
    def _cached_session(self, _mock_session_store):
        """Create a session with cache_name pre-set."""
        session = _mock_session_store.create(
            "https://www.youtube.com/watch?v=GcNu6wrLTJc",
            "general",
            video_title="Test",
            cache_name=TEST_CACHE_NAME,
            model="gemini-3.6-flash",
        )
        return session

    @pytest.fixture()
    def _uncached_session(self, _mock_session_store):
        """Create a session without cache_name."""
        session = _mock_session_store.create(
            "https://www.youtube.com/watch?v=GcNu6wrLTJc",
            "general",
            video_title="Test",
        )
        return session

    async def test_continue_session_passes_cached_content(
        self, _cached_session, _mock_session_store
    ):
        """GIVEN a session with cache_name WHEN continue called THEN cached_content set."""
        mock_response = MagicMock()
        mock_response.candidates = [
            MagicMock(content=MagicMock(parts=[MagicMock(text="Answer", thought=False)]))
        ]

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with (
            patch("video_research_mcp.tools.video.GeminiClient.get", return_value=mock_client),
            patch.object(cc_mod, "refresh_ttl", new_callable=AsyncMock, return_value=True),
            patch("video_research_mcp.tools.video.with_retry", side_effect=_passthrough_retry),
            patch("video_research_mcp.weaviate_store.store_session_turn", new_callable=AsyncMock),
        ):
            result = await video_continue_session(
                session_id=_cached_session.session_id, prompt="Summarize"
            )

        assert "error" not in result
        call_kwargs = mock_client.aio.models.generate_content.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
        assert config.cached_content == TEST_CACHE_NAME
        # Verify model matches what the cache was created for
        model_used = call_kwargs.kwargs.get("model")
        assert model_used == "gemini-3.6-flash"

    async def test_continue_session_uses_session_model_not_default(
        self, _mock_session_store
    ):
        """GIVEN a cached session with non-default model WHEN continue THEN uses session.model."""
        session = _mock_session_store.create(
            "https://www.youtube.com/watch?v=GcNu6wrLTJc",
            "general",
            video_title="Test",
            cache_name=TEST_CACHE_NAME,
            model="gemini-2.5-pro-custom",
        )

        mock_response = MagicMock()
        mock_response.candidates = [
            MagicMock(content=MagicMock(parts=[MagicMock(text="Answer", thought=False)]))
        ]
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with (
            patch("video_research_mcp.tools.video.GeminiClient.get", return_value=mock_client),
            patch.object(cc_mod, "refresh_ttl", new_callable=AsyncMock, return_value=True),
            patch("video_research_mcp.tools.video.with_retry", side_effect=_passthrough_retry),
            patch("video_research_mcp.weaviate_store.store_session_turn", new_callable=AsyncMock),
        ):
            result = await video_continue_session(
                session_id=session.session_id, prompt="Summarize"
            )

        assert "error" not in result
        model_used = mock_client.aio.models.generate_content.call_args.kwargs["model"]
        assert model_used == "gemini-2.5-pro-custom"

    async def test_continue_session_falls_back_when_cache_expired(
        self, _cached_session, _mock_session_store
    ):
        """GIVEN a cached session WHEN refresh_ttl fails THEN falls back to inline video."""
        mock_response = MagicMock()
        mock_response.candidates = [
            MagicMock(content=MagicMock(parts=[MagicMock(text="Answer", thought=False)]))
        ]
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with (
            patch("video_research_mcp.tools.video.GeminiClient.get", return_value=mock_client),
            patch.object(cc_mod, "refresh_ttl", new_callable=AsyncMock, return_value=False),
            patch("video_research_mcp.tools.video.with_retry", side_effect=_passthrough_retry),
            patch("video_research_mcp.weaviate_store.store_session_turn", new_callable=AsyncMock),
        ):
            result = await video_continue_session(
                session_id=_cached_session.session_id, prompt="Summarize"
            )

        assert "error" not in result
        call_kwargs = mock_client.aio.models.generate_content.call_args
        # Should NOT have cached_content since cache expired
        config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
        assert not hasattr(config, "cached_content") or config.cached_content is None
        # Should include video Part since we fell back
        contents = call_kwargs.kwargs.get("contents") or call_kwargs[1].get("contents")
        user_msg = contents[-1]
        assert len(user_msg.parts) == 2
        assert user_msg.parts[0].file_data is not None

    async def test_continue_session_omits_video_part_when_cached(
        self, _cached_session, _mock_session_store
    ):
        """GIVEN a cached session WHEN continue called THEN user content has text only."""
        mock_response = MagicMock()
        mock_response.candidates = [
            MagicMock(content=MagicMock(parts=[MagicMock(text="Answer", thought=False)]))
        ]

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with (
            patch("video_research_mcp.tools.video.GeminiClient.get", return_value=mock_client),
            patch.object(cc_mod, "refresh_ttl", new_callable=AsyncMock, return_value=True),
            patch("video_research_mcp.tools.video.with_retry", side_effect=_passthrough_retry),
            patch("video_research_mcp.weaviate_store.store_session_turn", new_callable=AsyncMock),
        ):
            await video_continue_session(
                session_id=_cached_session.session_id, prompt="Summarize"
            )

        call_kwargs = mock_client.aio.models.generate_content.call_args
        contents = call_kwargs.kwargs.get("contents") or call_kwargs[1].get("contents")
        user_msg = contents[-1]
        assert len(user_msg.parts) == 1
        assert user_msg.parts[0].text == "Summarize"
        assert user_msg.parts[0].file_data is None

    async def test_continue_session_refreshes_ttl(
        self, _cached_session, _mock_session_store
    ):
        """GIVEN a cached session WHEN continue called THEN refresh_ttl invoked."""
        mock_response = MagicMock()
        mock_response.candidates = [
            MagicMock(content=MagicMock(parts=[MagicMock(text="Answer", thought=False)]))
        ]

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with (
            patch("video_research_mcp.tools.video.GeminiClient.get", return_value=mock_client),
            patch.object(cc_mod, "refresh_ttl", new_callable=AsyncMock, return_value=True) as mock_refresh,
            patch("video_research_mcp.tools.video.with_retry", side_effect=_passthrough_retry),
            patch("video_research_mcp.weaviate_store.store_session_turn", new_callable=AsyncMock),
        ):
            await video_continue_session(
                session_id=_cached_session.session_id, prompt="Summarize"
            )

        mock_refresh.assert_called_once_with(TEST_CACHE_NAME)

    async def test_continue_session_includes_video_part_when_uncached(
        self, _uncached_session, _mock_session_store
    ):
        """GIVEN an uncached session WHEN continue called THEN user content has video+text."""
        mock_response = MagicMock()
        mock_response.candidates = [
            MagicMock(content=MagicMock(parts=[MagicMock(text="Answer", thought=False)]))
        ]

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with (
            patch("video_research_mcp.tools.video.GeminiClient.get", return_value=mock_client),
            patch("video_research_mcp.tools.video.with_retry", side_effect=_passthrough_retry),
            patch("video_research_mcp.weaviate_store.store_session_turn", new_callable=AsyncMock),
        ):
            await video_continue_session(
                session_id=_uncached_session.session_id, prompt="Summarize"
            )

        call_kwargs = mock_client.aio.models.generate_content.call_args
        contents = call_kwargs.kwargs.get("contents") or call_kwargs[1].get("contents")
        user_msg = contents[-1]
        assert len(user_msg.parts) == 2
        assert user_msg.parts[0].file_data is not None
        assert user_msg.parts[1].text == "Summarize"

        config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
        assert not hasattr(config, "cached_content") or config.cached_content is None

    async def test_continue_session_stores_local_filepath(self, _mock_session_store):
        """Session transcript writes include the session's local media path."""
        session = _mock_session_store.create(
            FILE_API_URI,
            "general",
            video_title="Test",
            local_filepath="/tmp/local-video.mp4",
        )

        mock_response = MagicMock()
        mock_response.candidates = [
            MagicMock(content=MagicMock(parts=[MagicMock(text="Answer", thought=False)]))
        ]
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with (
            patch("video_research_mcp.tools.video.GeminiClient.get", return_value=mock_client),
            patch("video_research_mcp.tools.video.with_retry", side_effect=_passthrough_retry),
            patch(
                "video_research_mcp.weaviate_store.store_session_turn",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            result = await video_continue_session(session_id=session.session_id, prompt="Summarize")

        assert "error" not in result
        assert mock_store.await_count == 1
        call_kwargs = mock_store.call_args.kwargs
        assert call_kwargs["local_filepath"] == "/tmp/local-video.mp4"


class TestLocalFileCaching:
    """Verify local file paths activate caching (via File API URI)."""

    async def test_local_file_session_creates_cache(
        self, mock_gemini_client, _mock_session_store
    ):
        """GIVEN a local file WHEN video_create_session(file_path=...) THEN returns cached status."""
        mock_gemini_client["generate"].return_value = "Local Video Title"

        mock_cached = MagicMock()
        mock_cached.name = TEST_CACHE_NAME

        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(return_value=mock_cached)

        with (
            patch(
                "video_research_mcp.tools.video._video_file_uri",
                new_callable=AsyncMock,
                return_value=(FILE_API_URI, "abcdef1234567890"),
            ),
            patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client),
        ):
            result = await video_create_session(file_path="/tmp/test.mp4")

        assert result["cache_status"] == "cached"
        assert result["source_type"] == "local"
        assert result["local_filepath"] == str(Path("/tmp/test.mp4").resolve())
        session = _mock_session_store.get(result["session_id"])
        assert session.cache_name == TEST_CACHE_NAME

    async def test_local_file_session_cache_failure_returns_reason(
        self, mock_gemini_client, _mock_session_store
    ):
        """GIVEN cache creation fails WHEN video_create_session(file_path=...) THEN returns reason."""
        mock_gemini_client["generate"].return_value = "Local Video Title"

        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(side_effect=Exception("Cache API down"))

        with (
            patch(
                "video_research_mcp.tools.video._video_file_uri",
                new_callable=AsyncMock,
                return_value=(FILE_API_URI, "abcdef1234567890"),
            ),
            patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client),
        ):
            result = await video_create_session(file_path="/tmp/test.mp4")

        assert result["cache_status"] == "uncached"
        assert result["cache_reason"] != ""
        assert result["local_filepath"] == str(Path("/tmp/test.mp4").resolve())
        session = _mock_session_store.get(result["session_id"])
        assert session.cache_name == ""

    async def test_video_analyze_prewarms_for_local_file(self, mock_gemini_client):
        """GIVEN a local file with File API URI WHEN video_analyze THEN calls prewarm_cache."""
        from video_research_mcp.models.video import VideoResult

        mock_gemini_client["generate_structured"].return_value = VideoResult(
            title="Test", summary="Summary", key_points=["point"]
        )

        with (
            patch(
                "video_research_mcp.tools.video._video_file_content",
                new_callable=AsyncMock,
                return_value=(MagicMock(), "abcdef1234567890", FILE_API_URI),
            ),
            patch.object(cc_mod, "start_prewarm", return_value=MagicMock()) as mock_prewarm,
        ):
            result = await video_analyze(file_path="/tmp/test.mp4", use_cache=False)

        assert "error" not in result
        mock_prewarm.assert_called_once()

    async def test_local_file_small_skips_prewarm(self, mock_gemini_client):
        """GIVEN a small local file (inline bytes, no URI) WHEN video_analyze THEN skips prewarm."""
        from video_research_mcp.models.video import VideoResult

        mock_gemini_client["generate_structured"].return_value = VideoResult(
            title="Test", summary="Summary", key_points=["point"]
        )

        with (
            patch(
                "video_research_mcp.tools.video._video_file_content",
                new_callable=AsyncMock,
                return_value=(MagicMock(), "abcdef1234567890", ""),
            ),
            patch.object(cc_mod, "start_prewarm", return_value=MagicMock()) as mock_prewarm,
        ):
            result = await video_analyze(file_path="/tmp/small.mp4", use_cache=False)

        assert "error" not in result
        mock_prewarm.assert_not_called()
