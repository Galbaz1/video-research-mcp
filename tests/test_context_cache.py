"""Tests for the Gemini context cache registry."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from google.genai import types

import video_research_mcp.config as cfg_mod
import video_research_mcp.context_cache as cc_mod


@pytest.fixture(autouse=True)
def _clean_config(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    cfg_mod._config = None
    yield
    cfg_mod._config = None


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Ensure cache registry, pending, suppressed, and failures are empty between tests."""
    cc_mod._registry.clear()
    cc_mod._pending.clear()
    cc_mod._suppressed.clear()
    cc_mod._last_failure.clear()
    cc_mod._loaded = True  # Prevent disk load during unit tests
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


def _video_parts() -> list[types.Part]:
    return [types.Part(file_data=types.FileData(file_uri="https://www.youtube.com/watch?v=abc"))]


class TestGetOrCreate:
    async def test_creates_cache_on_first_call(self):
        """GIVEN no existing cache WHEN get_or_create called THEN creates one."""
        mock_cached = MagicMock()
        mock_cached.name = "cachedContents/xyz123"

        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(return_value=mock_cached)

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            result = await cc_mod.get_or_create("abc", _video_parts(), "gemini-pro")

        assert result == "cachedContents/xyz123"
        assert cc_mod._registry[("abc", "gemini-pro")] == "cachedContents/xyz123"

    async def test_returns_cached_on_second_call(self):
        """GIVEN a registry entry WHEN get_or_create called THEN validates and returns it."""
        cc_mod._registry[("abc", "gemini-pro")] = "cachedContents/existing"

        mock_cached = MagicMock()
        mock_cached.name = "cachedContents/existing"

        mock_client = MagicMock()
        mock_client.aio.caches.get = AsyncMock(return_value=mock_cached)

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            result = await cc_mod.get_or_create("abc", _video_parts(), "gemini-pro")

        assert result == "cachedContents/existing"
        mock_client.aio.caches.create.assert_not_called()

    async def test_recreates_on_stale_cache(self):
        """GIVEN a stale registry entry WHEN validated THEN recreates cache."""
        cc_mod._registry[("abc", "gemini-pro")] = "cachedContents/stale"

        mock_new = MagicMock()
        mock_new.name = "cachedContents/new123"

        mock_client = MagicMock()
        mock_client.aio.caches.get = AsyncMock(side_effect=Exception("NOT_FOUND"))
        mock_client.aio.caches.create = AsyncMock(return_value=mock_new)

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            result = await cc_mod.get_or_create("abc", _video_parts(), "gemini-pro")

        assert result == "cachedContents/new123"

    async def test_stale_eviction_persisted_on_recreate_failure(self, _isolate_registry_path):
        """GIVEN a stale registry entry WHEN recreate fails THEN eviction is persisted to disk."""
        cc_mod._registry[("abc", "gemini-pro")] = "cachedContents/stale"

        mock_client = MagicMock()
        mock_client.aio.caches.get = AsyncMock(side_effect=Exception("NOT_FOUND"))
        mock_client.aio.caches.create = AsyncMock(side_effect=Exception("API error"))

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            result = await cc_mod.get_or_create("abc", _video_parts(), "gemini-pro")

        assert result is None
        assert ("abc", "gemini-pro") not in cc_mod._registry

        # Verify eviction was persisted — reload from disk should NOT have the stale key
        cc_mod._registry.clear()
        cc_mod._loaded = False
        cc_mod._load_registry()
        assert ("abc", "gemini-pro") not in cc_mod._registry

    async def test_returns_none_on_create_failure(self):
        """GIVEN no registry entry WHEN create fails THEN returns None."""
        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(side_effect=Exception("API error"))

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            result = await cc_mod.get_or_create("abc", _video_parts(), "gemini-pro")

        assert result is None
        assert ("abc", "gemini-pro") not in cc_mod._registry


class TestRefreshTtl:
    async def test_refresh_success(self):
        """GIVEN an active cache WHEN refresh_ttl called THEN returns True."""
        mock_client = MagicMock()
        mock_client.aio.caches.update = AsyncMock()

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            result = await cc_mod.refresh_ttl("cachedContents/xyz")

        assert result is True
        mock_client.aio.caches.update.assert_called_once()

    async def test_refresh_failure(self):
        """GIVEN an expired cache WHEN refresh_ttl called THEN returns False."""
        mock_client = MagicMock()
        mock_client.aio.caches.update = AsyncMock(side_effect=Exception("NOT_FOUND"))

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            result = await cc_mod.refresh_ttl("cachedContents/expired")

        assert result is False


class TestLookup:
    def test_lookup_hit(self):
        """GIVEN a registry entry WHEN lookup called THEN returns name."""
        cc_mod._registry[("vid1", "model1")] = "cachedContents/abc"
        assert cc_mod.lookup("vid1", "model1") == "cachedContents/abc"

    def test_lookup_miss(self):
        """GIVEN no registry entry WHEN lookup called THEN returns None."""
        assert cc_mod.lookup("unknown", "model1") is None


class TestPrewarmAndLookupOrAwait:
    """Verify start_prewarm tracking and lookup_or_await bridging."""

    @pytest.fixture(autouse=True)
    def _clean_pending(self):
        cc_mod._pending.clear()
        yield
        cc_mod._pending.clear()

    async def test_lookup_or_await_returns_after_prewarm_completes(self):
        """GIVEN a pending prewarm WHEN lookup_or_await called THEN awaits and returns."""
        mock_cached = MagicMock()
        mock_cached.name = "cachedContents/warm123"

        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(return_value=mock_cached)

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            cc_mod.start_prewarm("vid1", _video_parts(), "model-a")
            result = await cc_mod.lookup_or_await("vid1", "model-a", timeout=5.0)

        assert result == "cachedContents/warm123"

    async def test_lookup_or_await_times_out_gracefully(self):
        """GIVEN a slow prewarm WHEN timeout reached THEN returns None."""
        async def slow_create(*args, **kwargs):
            await asyncio.sleep(10)
            return MagicMock(name="cachedContents/never")

        mock_client = MagicMock()
        mock_client.aio.caches.create = slow_create

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            cc_mod.start_prewarm("vid1", _video_parts(), "model-a")
            result = await cc_mod.lookup_or_await("vid1", "model-a", timeout=0.1)

        assert result is None

    async def test_lookup_or_await_returns_immediately_on_registry_hit(self):
        """GIVEN a registry hit WHEN lookup_or_await called THEN returns without awaiting."""
        cc_mod._registry[("vid1", "model-a")] = "cachedContents/existing"
        result = await cc_mod.lookup_or_await("vid1", "model-a")
        assert result == "cachedContents/existing"

    async def test_lookup_or_await_returns_none_when_no_pending(self):
        """GIVEN no registry and no pending WHEN lookup_or_await THEN returns None."""
        result = await cc_mod.lookup_or_await("vid1", "model-a")
        assert result is None

    async def test_start_prewarm_deduplicates_concurrent_calls(self):
        """GIVEN an in-flight prewarm WHEN start_prewarm called again THEN returns same task."""
        mock_cached = MagicMock()
        mock_cached.name = "cachedContents/dedup"

        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(return_value=mock_cached)

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            task1 = cc_mod.start_prewarm("vid1", _video_parts(), "model-a")
            task2 = cc_mod.start_prewarm("vid1", _video_parts(), "model-a")

        assert task1 is task2
        await task1

    async def test_start_prewarm_callback_does_not_remove_replacement(self):
        """GIVEN task1 replaced by task2 WHEN task1 completes THEN task2 stays in _pending."""
        mock_cached = MagicMock()
        mock_cached.name = "cachedContents/first"

        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(return_value=mock_cached)

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            task1 = cc_mod.start_prewarm("vid1", _video_parts(), "model-a")
            await task1  # complete task1
            await asyncio.sleep(0)  # let callback run

            # task1 is done, so start_prewarm creates a new task2
            task2 = cc_mod.start_prewarm("vid1", _video_parts(), "model-a")

        assert task1 is not task2
        assert cc_mod._pending.get(("vid1", "model-a")) is task2
        await task2

    async def test_start_prewarm_cleans_up_pending_on_completion(self):
        """GIVEN a prewarm task WHEN it completes THEN key removed from _pending."""
        mock_cached = MagicMock()
        mock_cached.name = "cachedContents/done"

        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(return_value=mock_cached)

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            task = cc_mod.start_prewarm("vid1", _video_parts(), "model-a")
            assert ("vid1", "model-a") in cc_mod._pending
            await task

        # done_callback may need an event loop iteration
        await asyncio.sleep(0)
        assert ("vid1", "model-a") not in cc_mod._pending


class TestTokenSuppression:
    """Verify min-token failure suppression for short videos."""

    async def test_suppresses_after_min_token_failure(self):
        """GIVEN a create that fails with 'too few tokens' WHEN retried THEN skipped."""
        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(
            side_effect=Exception("CachedContent has too few tokens")
        )

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            result1 = await cc_mod.get_or_create("short-vid", _video_parts(), "gemini-pro")

        assert result1 is None
        assert ("short-vid", "gemini-pro") in cc_mod._suppressed

        # Second call should be suppressed (no API call)
        with patch("video_research_mcp.context_cache.GeminiClient.get") as mock_get:
            result2 = await cc_mod.get_or_create("short-vid", _video_parts(), "gemini-pro")

        assert result2 is None
        mock_get.assert_not_called()

    async def test_suppression_does_not_block_other_models(self):
        """GIVEN Pro failure WHEN Flash attempted THEN not suppressed."""
        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(
            side_effect=Exception("CachedContent has too few tokens")
        )

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            await cc_mod.get_or_create("short-vid", _video_parts(), "gemini-pro")

        assert ("short-vid", "gemini-pro") in cc_mod._suppressed
        assert ("short-vid", "gemini-flash") not in cc_mod._suppressed

        # Flash should still be attempted
        mock_cached = MagicMock()
        mock_cached.name = "cachedContents/flash-ok"
        mock_client2 = MagicMock()
        mock_client2.aio.caches.create = AsyncMock(return_value=mock_cached)

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client2):
            result = await cc_mod.get_or_create("short-vid", _video_parts(), "gemini-flash")

        assert result == "cachedContents/flash-ok"

    async def test_suppression_cleared_on_clear(self):
        """GIVEN suppressed entries WHEN clear() called THEN suppression set emptied."""
        cc_mod._suppressed.add(("short-vid", "gemini-pro"))
        cc_mod._registry[("a", "m")] = "cachedContents/1"

        mock_client = MagicMock()
        mock_client.aio.caches.delete = AsyncMock()

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            await cc_mod.clear()

        assert len(cc_mod._suppressed) == 0

    async def test_suppression_cleared_on_clear_empty_registry(self):
        """GIVEN suppressed entries and empty registry WHEN clear() THEN suppression cleared."""
        cc_mod._suppressed.add(("x", "model"))
        assert len(cc_mod._registry) == 0

        count = await cc_mod.clear()

        assert count == 0
        assert len(cc_mod._suppressed) == 0

    async def test_non_token_error_not_suppressed(self):
        """GIVEN a create that fails with generic error WHEN checked THEN not suppressed."""
        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(
            side_effect=Exception("Internal server error")
        )

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            await cc_mod.get_or_create("other-vid", _video_parts(), "gemini-pro")

        assert ("other-vid", "gemini-pro") not in cc_mod._suppressed

    async def test_suppression_minimum_keyword(self):
        """GIVEN a create that fails with 'minimum' keyword THEN suppressed."""
        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(
            side_effect=Exception("Content does not meet minimum token requirement")
        )

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            await cc_mod.get_or_create("tiny-vid", _video_parts(), "gemini-pro")

        assert ("tiny-vid", "gemini-pro") in cc_mod._suppressed


class TestClear:
    async def test_clear_empty_registry_without_api_key(self, monkeypatch):
        """GIVEN empty registry and no key WHEN clear called THEN no client lookup."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

        with patch("video_research_mcp.context_cache.GeminiClient.get") as mock_get:
            count = await cc_mod.clear()

        assert count == 0
        assert len(cc_mod._registry) == 0
        mock_get.assert_not_called()

    async def test_clear_client_init_failure_clears_registry(self):
        """GIVEN registry entries and no client WHEN clear called THEN registry is cleared."""
        cc_mod._registry[("a", "m")] = "cachedContents/1"

        with patch(
            "video_research_mcp.context_cache.GeminiClient.get",
            side_effect=ValueError("No Gemini API key"),
        ):
            count = await cc_mod.clear()

        assert count == 0
        assert len(cc_mod._registry) == 0

    async def test_clear_deletes_all(self):
        """GIVEN multiple registry entries WHEN clear called THEN all deleted."""
        cc_mod._registry[("a", "m")] = "cachedContents/1"
        cc_mod._registry[("b", "m")] = "cachedContents/2"

        mock_client = MagicMock()
        mock_client.aio.caches.delete = AsyncMock()

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            count = await cc_mod.clear()

        assert count == 2
        assert len(cc_mod._registry) == 0

    async def test_clear_tolerates_delete_failures(self):
        """GIVEN registry entries WHEN delete fails THEN registry still cleared."""
        cc_mod._registry[("a", "m")] = "cachedContents/1"

        mock_client = MagicMock()
        mock_client.aio.caches.delete = AsyncMock(side_effect=Exception("fail"))

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            count = await cc_mod.clear()

        assert count == 0
        assert len(cc_mod._registry) == 0


class TestSessionCacheFields:
    """Verify cache_name and model fields persist through session store + DB."""

    def test_session_create_with_cache_fields(self):
        """GIVEN cache_name and model WHEN session created THEN fields stored."""
        from video_research_mcp.sessions import SessionStore

        store = SessionStore()
        session = store.create(
            "https://youtube.com/watch?v=abc", "general",
            video_title="Test",
            cache_name="cachedContents/xyz",
            model="gemini-pro",
        )
        assert session.cache_name == "cachedContents/xyz"
        assert session.model == "gemini-pro"

    def test_session_cache_fields_default_empty(self):
        """GIVEN no cache args WHEN session created THEN fields are empty strings."""
        from video_research_mcp.sessions import SessionStore

        store = SessionStore()
        session = store.create("https://youtube.com/watch?v=abc", "general")
        assert session.cache_name == ""
        assert session.model == ""

    def test_persistence_roundtrip_with_cache_fields(self, tmp_path):
        """GIVEN cache fields WHEN persisted to SQLite THEN recoverable."""
        from video_research_mcp.sessions import SessionStore

        db_path = str(tmp_path / "sessions.db")
        store = SessionStore(db_path=db_path)
        session = store.create(
            "https://youtube.com/watch?v=abc", "general",
            video_title="Test",
            cache_name="cachedContents/persist-test",
            model="gemini-3.1-pro-preview",
        )

        store2 = SessionStore(db_path=db_path)
        recovered = store2.get(session.session_id)
        assert recovered is not None
        assert recovered.cache_name == "cachedContents/persist-test"
        assert recovered.model == "gemini-3.1-pro-preview"

    def test_migration_adds_columns(self, tmp_path):
        """GIVEN a DB without cache columns WHEN SessionDB opened THEN migrates."""
        import sqlite3

        db_path = str(tmp_path / "old.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                mode TEXT NOT NULL,
                video_title TEXT NOT NULL DEFAULT '',
                history TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                last_active TEXT NOT NULL,
                turn_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            INSERT INTO sessions VALUES (
                'old1', 'url', 'general', 'Title', '[]',
                '2025-01-01T00:00:00', '2025-01-01T00:00:00', 0
            )
        """)
        conn.commit()
        conn.close()

        from video_research_mcp.persistence import SessionDB

        db = SessionDB(db_path)
        loaded = db.load_sync("old1")
        assert loaded is not None
        assert loaded.cache_name == ""
        assert loaded.model == ""
        db.close()


class TestShutdownBehavior:
    """Verify shutdown respects clear_cache_on_shutdown config flag."""

    async def test_shutdown_preserves_registry_by_default(self, _isolate_registry_path):
        """GIVEN default config WHEN lifespan exits THEN registry file is untouched."""
        cc_mod._registry[("vid1", "model-a")] = "cachedContents/aaa"
        cc_mod._save_registry()
        assert _isolate_registry_path.exists()

        from video_research_mcp.server import _lifespan

        with (
            patch("video_research_mcp.server.WeaviateClient.aclose", new_callable=AsyncMock),
            patch("video_research_mcp.server.GeminiClient.close_all", new_callable=AsyncMock, return_value=0),
        ):
            async with _lifespan(None):
                pass

        # Registry should still be on disk with data
        cc_mod._registry.clear()
        cc_mod._loaded = False
        cc_mod._load_registry()
        assert ("vid1", "model-a") in cc_mod._registry

    async def test_shutdown_clears_when_configured(self, monkeypatch, _isolate_registry_path):
        """GIVEN clear_cache_on_shutdown=True WHEN lifespan exits THEN registry is cleared."""
        cfg_mod._config = None
        monkeypatch.setenv("CLEAR_CACHE_ON_SHUTDOWN", "true")
        cc_mod._registry[("vid1", "model-a")] = "cachedContents/aaa"
        cc_mod._save_registry()

        mock_client = MagicMock()
        mock_client.aio.caches.delete = AsyncMock()

        from video_research_mcp.server import _lifespan

        with (
            patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client),
            patch("video_research_mcp.server.WeaviateClient.aclose", new_callable=AsyncMock),
            patch("video_research_mcp.server.GeminiClient.close_all", new_callable=AsyncMock, return_value=0),
        ):
            async with _lifespan(None):
                pass

        assert len(cc_mod._registry) == 0


class TestRegistryPersistence:
    """Verify registry save/load roundtrip and GC behavior."""

    def test_save_and_load_roundtrip(self, _isolate_registry_path):
        """GIVEN populated registry WHEN saved and reloaded THEN entries restored."""
        cc_mod._registry[("vid1", "model-a")] = "cachedContents/aaa"
        cc_mod._registry[("vid2", "model-b")] = "cachedContents/bbb"
        cc_mod._save_registry()

        cc_mod._registry.clear()
        cc_mod._loaded = False
        cc_mod._load_registry()

        assert cc_mod._registry[("vid1", "model-a")] == "cachedContents/aaa"
        assert cc_mod._registry[("vid2", "model-b")] == "cachedContents/bbb"

    def test_load_missing_file(self):
        """GIVEN no file on disk WHEN load called THEN empty registry, no error."""
        cc_mod._loaded = False
        cc_mod._load_registry()
        assert len(cc_mod._registry) == 0

    def test_load_corrupted_file(self, _isolate_registry_path):
        """GIVEN invalid JSON WHEN load called THEN falls back to empty."""
        _isolate_registry_path.write_text("not valid json {{{")
        cc_mod._loaded = False
        cc_mod._load_registry()
        assert len(cc_mod._registry) == 0

    def test_load_ignores_invalid_shape_entries(self, _isolate_registry_path):
        """GIVEN mixed-shape registry JSON WHEN load called THEN only valid mappings are loaded."""
        _isolate_registry_path.write_text(
            (
                '{"good":{"model-a":"cachedContents/ok"},'
                '"bad_cid":["not-a-dict"],'
                '"bad_models":{"model-b":42}}'
            )
        )
        cc_mod._loaded = False
        cc_mod._load_registry()

        assert cc_mod._registry == {("good", "model-a"): "cachedContents/ok"}

    def test_gc_caps_at_max_entries(self, _isolate_registry_path):
        """GIVEN 250 entries WHEN saved THEN capped at _MAX_REGISTRY_ENTRIES."""
        for i in range(250):
            cc_mod._registry[(f"vid{i}", "model")] = f"cachedContents/{i}"
        cc_mod._save_registry()

        assert len(cc_mod._registry) <= cc_mod._MAX_REGISTRY_ENTRIES

        cc_mod._registry.clear()
        cc_mod._loaded = False
        cc_mod._load_registry()
        assert len(cc_mod._registry) == cc_mod._MAX_REGISTRY_ENTRIES


class TestFailureReason:
    """Verify failure_reason() returns the correct reason for each failure mode."""

    def test_suppressed_returns_reason(self):
        """GIVEN a suppressed key WHEN failure_reason called THEN returns suppression reason."""
        cc_mod._suppressed.add(("short-vid", "gemini-pro"))
        assert cc_mod.failure_reason("short-vid", "gemini-pro") == "suppressed:too_few_tokens"

    def test_api_error_returns_reason(self):
        """GIVEN a last_failure entry WHEN failure_reason called THEN returns it."""
        cc_mod._last_failure[("vid1", "model")] = "api_error:ValueError"
        assert cc_mod.failure_reason("vid1", "model") == "api_error:ValueError"

    def test_no_failure_returns_empty(self):
        """GIVEN no failure recorded WHEN failure_reason called THEN returns empty string."""
        assert cc_mod.failure_reason("unknown", "model") == ""

    def test_suppressed_takes_precedence(self):
        """GIVEN both suppressed and last_failure WHEN failure_reason called THEN suppressed wins."""
        key = ("vid1", "model")
        cc_mod._suppressed.add(key)
        cc_mod._last_failure[key] = "api_error:RuntimeError"
        assert cc_mod.failure_reason("vid1", "model") == "suppressed:too_few_tokens"

    async def test_last_failure_cleared_on_success(self):
        """GIVEN a previous failure WHEN get_or_create succeeds THEN failure cleared."""
        cc_mod._last_failure[("abc", "gemini-pro")] = "api_error:RuntimeError"

        mock_cached = MagicMock()
        mock_cached.name = "cachedContents/success"

        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(return_value=mock_cached)

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            result = await cc_mod.get_or_create("abc", _video_parts(), "gemini-pro")

        assert result == "cachedContents/success"
        assert ("abc", "gemini-pro") not in cc_mod._last_failure

    async def test_get_or_create_records_api_error(self):
        """GIVEN a non-token API failure WHEN get_or_create called THEN records api_error."""
        mock_client = MagicMock()
        mock_client.aio.caches.create = AsyncMock(side_effect=RuntimeError("quota exceeded"))

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            await cc_mod.get_or_create("vid1", _video_parts(), "gemini-pro")

        reason = cc_mod._last_failure[("vid1", "gemini-pro")]
        assert reason.startswith("api_error:RuntimeError:")
        assert "quota exceeded" in reason

    async def test_get_or_create_records_stale_eviction(self):
        """GIVEN a stale registry entry WHEN validation fails THEN records stale_cache_evicted."""
        cc_mod._registry[("abc", "gemini-pro")] = "cachedContents/stale"

        mock_cached = MagicMock()
        mock_cached.name = "cachedContents/new"

        mock_client = MagicMock()
        mock_client.aio.caches.get = AsyncMock(side_effect=Exception("NOT_FOUND"))
        mock_client.aio.caches.create = AsyncMock(return_value=mock_cached)

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            result = await cc_mod.get_or_create("abc", _video_parts(), "gemini-pro")

        # Successful recreate clears the stale failure
        assert result == "cachedContents/new"
        assert ("abc", "gemini-pro") not in cc_mod._last_failure


class TestDiagnostics:
    """Verify diagnostics() returns a complete snapshot."""

    def test_diagnostics_returns_snapshot(self):
        """GIVEN various cache states WHEN diagnostics called THEN returns structured dict."""
        cc_mod._registry[("vid1", "model-a")] = "cachedContents/aaa"
        cc_mod._suppressed.add(("short", "model-a"))
        cc_mod._last_failure[("fail", "model-a")] = "api_error:TimeoutError"

        result = cc_mod.diagnostics()

        assert result["registry"] == {"vid1/model-a": "cachedContents/aaa"}
        assert "short/model-a" in result["suppressed"]
        assert result["recent_failures"] == {"fail/model-a": "api_error:TimeoutError"}
        assert isinstance(result["pending"], list)

    def test_diagnostics_empty_state(self):
        """GIVEN clean state WHEN diagnostics called THEN returns empty collections."""
        result = cc_mod.diagnostics()
        assert result == {"registry": {}, "suppressed": [], "pending": [], "recent_failures": {}}

    async def test_clear_resets_last_failure(self):
        """GIVEN failures recorded WHEN clear() called THEN last_failure emptied."""
        cc_mod._last_failure[("vid1", "model")] = "api_error:ValueError"
        cc_mod._registry[("a", "m")] = "cachedContents/1"

        mock_client = MagicMock()
        mock_client.aio.caches.delete = AsyncMock()

        with patch("video_research_mcp.context_cache.GeminiClient.get", return_value=mock_client):
            await cc_mod.clear()

        assert len(cc_mod._last_failure) == 0
