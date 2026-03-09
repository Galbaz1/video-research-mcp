"""Tests for Deep Research (Interactions API) tools."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from video_research_mcp.models.research_web import (
    DeepResearchFollowup,
    DeepResearchLaunch,
    DeepResearchResult,
    DeepResearchSource,
)
from video_research_mcp.tools.research_web import (
    _ACTIVE_TTL_SECONDS,
    _MAX_TRACKED,
    _TTL_SECONDS,
    _evict_stale,
    _extract_report,
    _extract_usage,
    _launch_times,
    research_web,
    research_web_cancel,
    research_web_followup,
    research_web_status,
)


def _make_interaction(
    interaction_id: str = "test-interaction-123",
    status: str = "completed",
    outputs: list | None = None,
    usage: object | None = None,
):
    """Build a mock Interaction object."""
    return SimpleNamespace(
        id=interaction_id,
        status=status,
        outputs=outputs or [],
        usage=usage,
    )


def _make_text_content(text: str):
    return SimpleNamespace(type="text", text=text)


def _make_search_result_content(url: str, title: str = ""):
    return SimpleNamespace(
        type="googleSearchResult",
        result=SimpleNamespace(url=url, title=title),
    )


def _make_url_context_content(url: str, status: str = "ok"):
    return SimpleNamespace(
        type="urlContextResult",
        result=SimpleNamespace(url=url, status=status),
    )


def _make_turn(contents: list):
    return SimpleNamespace(content=contents, role="model")


def _make_usage(input_tokens=100, output_tokens=200, total=300, thought=50):
    return SimpleNamespace(
        total_input_tokens=input_tokens,
        total_output_tokens=output_tokens,
        total_tokens=total,
        total_thought_tokens=thought,
    )


# ── _extract_report ───────────────────────────────────────────────────────


class TestExtractReport:
    def test_extracts_text_and_sources(self):
        """GIVEN outputs with text and search results WHEN extracting THEN both are returned."""
        interaction = _make_interaction(outputs=[
            _make_turn([
                _make_text_content("# Report Title"),
                _make_search_result_content("https://example.com", "Example"),
                _make_text_content("## Section 1"),
                _make_url_context_content("https://other.com", "ok"),
            ]),
        ])
        text, sources = _extract_report(interaction)

        assert "# Report Title" in text
        assert "## Section 1" in text
        assert len(sources) == 2
        assert sources[0].url == "https://example.com"
        assert sources[0].title == "Example"
        assert sources[1].url == "https://other.com"
        assert sources[1].status == "ok"

    def test_empty_outputs(self):
        """GIVEN no outputs WHEN extracting THEN empty results."""
        interaction = _make_interaction(outputs=[])
        text, sources = _extract_report(interaction)
        assert text == ""
        assert sources == []

    def test_none_outputs(self):
        """GIVEN None outputs WHEN extracting THEN empty results."""
        interaction = _make_interaction(outputs=None)
        text, sources = _extract_report(interaction)
        assert text == ""
        assert sources == []

    def test_multiple_turns(self):
        """GIVEN multiple turns WHEN extracting THEN all text is concatenated."""
        interaction = _make_interaction(outputs=[
            _make_turn([_make_text_content("Part 1")]),
            _make_turn([_make_text_content("Part 2")]),
        ])
        text, _ = _extract_report(interaction)
        assert "Part 1" in text
        assert "Part 2" in text

    def test_extracts_direct_turn_text(self):
        """GIVEN turn with text attr and no content WHEN extracting THEN text is captured."""
        turn = SimpleNamespace(text="# Full Report\n\nDetailed findings here.", content=None)
        interaction = _make_interaction(outputs=[turn])
        text, sources = _extract_report(interaction)
        assert "Full Report" in text
        assert "Detailed findings" in text
        assert sources == []

    def test_extracts_both_turn_text_and_content(self):
        """GIVEN turn with both text attr and content array WHEN extracting THEN both captured."""
        turn = SimpleNamespace(
            text="Direct text from turn",
            content=[_make_text_content("Content array text")],
        )
        interaction = _make_interaction(outputs=[turn])
        text, _ = _extract_report(interaction)
        assert "Direct text from turn" in text
        assert "Content array text" in text


# ── _extract_usage ────────────────────────────────────────────────────────


class TestExtractUsage:
    def test_extracts_usage_fields(self):
        usage = _extract_usage(_make_interaction(usage=_make_usage()))
        assert usage["total_input_tokens"] == 100
        assert usage["total_output_tokens"] == 200
        assert usage["total_tokens"] == 300
        assert usage["total_thought_tokens"] == 50

    def test_none_usage(self):
        assert _extract_usage(_make_interaction(usage=None)) == {}


# ── research_web ──────────────────────────────────────────────────────────


class TestResearchWeb:
    async def test_launch_returns_interaction_id(self, mock_gemini_client):
        """GIVEN valid topic WHEN launching THEN returns interaction_id and status."""
        mock_interaction = _make_interaction(
            interaction_id="dr-abc-123",
            status="in_progress",
        )
        mock_client = MagicMock()
        mock_client.aio.interactions.create = AsyncMock(return_value=mock_interaction)
        mock_gemini_client["get"].return_value = mock_client

        result = await research_web(
            topic="Impact of quantum computing on cryptography in 2026",
        )

        assert result["interaction_id"] == "dr-abc-123"
        assert result["status"] == "in_progress"
        assert result["estimated_minutes"] == "10-20"
        assert "dr-abc-123" in _launch_times
        assert "time" in _launch_times["dr-abc-123"]
        assert "topic" in _launch_times["dr-abc-123"]
        _launch_times.pop("dr-abc-123", None)  # cleanup

    async def test_launch_with_output_format(self, mock_gemini_client):
        """GIVEN output_format WHEN launching THEN prompt includes format."""
        mock_interaction = _make_interaction(
            interaction_id="dr-fmt-456",
            status="in_progress",
        )
        mock_client = MagicMock()
        mock_client.aio.interactions.create = AsyncMock(return_value=mock_interaction)
        mock_gemini_client["get"].return_value = mock_client

        await research_web(
            topic="Quantum computing impact analysis",
            output_format="Executive summary + data tables",
        )

        call_kwargs = mock_client.aio.interactions.create.call_args.kwargs
        assert "Output format:" in call_kwargs["input"]
        assert "Executive summary + data tables" in call_kwargs["input"]
        _launch_times.pop("dr-fmt-456", None)

    async def test_launch_uses_configured_agent(self, mock_gemini_client, clean_config, monkeypatch):
        """GIVEN custom agent env var WHEN launching THEN uses configured agent."""
        monkeypatch.setenv("DEEP_RESEARCH_AGENT", "custom-agent-v2")
        mock_interaction = _make_interaction(interaction_id="dr-custom", status="in_progress")
        mock_client = MagicMock()
        mock_client.aio.interactions.create = AsyncMock(return_value=mock_interaction)
        mock_gemini_client["get"].return_value = mock_client

        await research_web(topic="Test topic for agent config verification")

        call_kwargs = mock_client.aio.interactions.create.call_args.kwargs
        assert call_kwargs["agent"] == "custom-agent-v2"
        _launch_times.pop("dr-custom", None)

    async def test_launch_blocked_when_active_task(self, mock_gemini_client):
        """GIVEN active interaction <30 min old WHEN launching THEN returns error."""
        _launch_times["active-task-1"] = {"time": time.time() - 300, "topic": "active"}

        result = await research_web(topic="New topic that should be blocked by guard")

        assert "error" in result
        assert "already in progress" in result["error"]
        assert "active-task-1" in result["error"]
        _launch_times.pop("active-task-1", None)

    async def test_launch_allowed_after_stale_task(self, mock_gemini_client):
        """GIVEN stale interaction >30 min old WHEN launching THEN proceeds normally."""
        _launch_times["stale-task-1"] = {
            "time": time.time() - _ACTIVE_TTL_SECONDS - 1, "topic": "stale",
        }
        mock_interaction = _make_interaction(interaction_id="new-task-1", status="in_progress")
        mock_client = MagicMock()
        mock_client.aio.interactions.create = AsyncMock(return_value=mock_interaction)
        mock_gemini_client["get"].return_value = mock_client

        result = await research_web(topic="Topic that should succeed because stale")

        assert result["interaction_id"] == "new-task-1"
        assert result["status"] == "in_progress"
        _launch_times.pop("new-task-1", None)
        _launch_times.pop("stale-task-1", None)

    async def test_launch_error_returns_tool_error(self, mock_gemini_client):
        """GIVEN API error WHEN launching THEN returns tool error."""
        mock_client = MagicMock()
        mock_client.aio.interactions.create = AsyncMock(
            side_effect=RuntimeError("API unavailable"),
        )
        mock_gemini_client["get"].return_value = mock_client

        result = await research_web(topic="Test topic that triggers an error")

        assert "error" in result
        assert "API unavailable" in result["error"]


# ── research_web_status ───────────────────────────────────────────────────


class TestResearchWebStatus:
    async def test_completed_returns_full_report(self, mock_gemini_client):
        """GIVEN completed interaction WHEN polling THEN returns report with sources."""
        interaction = _make_interaction(
            outputs=[_make_turn([
                _make_text_content("# Deep Research Report\n\nFindings here."),
                _make_search_result_content("https://source1.com", "Source 1"),
                _make_search_result_content("https://source2.com", "Source 2"),
            ])],
            usage=_make_usage(500, 8000, 8500, 200),
        )
        mock_client = MagicMock()
        mock_client.aio.interactions.get = AsyncMock(return_value=interaction)
        mock_gemini_client["get"].return_value = mock_client

        _launch_times["test-interaction-123"] = {"time": time.time() - 600, "topic": "test topic"}

        with patch("video_research_mcp.weaviate_store.store_deep_research", new_callable=AsyncMock) as mock_store:
            mock_store.return_value = "uuid-1"
            result = await research_web_status(interaction_id="test-interaction-123")

        assert result["status"] == "completed"
        assert "Deep Research Report" in result["report_text"]
        assert result["source_count"] == 2
        assert result["sources"][0]["url"] == "https://source1.com"
        assert result["duration_seconds"] is not None
        assert result["duration_seconds"] >= 600
        assert result["usage"]["total_tokens"] == 8500

    async def test_in_progress_returns_status(self, mock_gemini_client):
        """GIVEN in-progress interaction WHEN polling THEN returns status only."""
        interaction = _make_interaction(status="in_progress")
        mock_client = MagicMock()
        mock_client.aio.interactions.get = AsyncMock(return_value=interaction)
        mock_gemini_client["get"].return_value = mock_client

        result = await research_web_status(interaction_id="test-interaction-123")

        assert result["status"] == "in_progress"
        assert "report_text" not in result

    async def test_error_returns_tool_error(self, mock_gemini_client):
        """GIVEN API error WHEN polling THEN returns tool error."""
        mock_client = MagicMock()
        mock_client.aio.interactions.get = AsyncMock(
            side_effect=RuntimeError("Not found"),
        )
        mock_gemini_client["get"].return_value = mock_client

        result = await research_web_status(interaction_id="nonexistent-id")

        assert "error" in result

    async def test_status_retries_on_transient_403(self, mock_gemini_client):
        """GIVEN 403 on first attempt WHEN polling THEN retries and succeeds."""
        interaction = _make_interaction(status="in_progress")
        mock_client = MagicMock()
        mock_client.aio.interactions.get = AsyncMock(
            side_effect=[RuntimeError("403 Forbidden"), interaction],
        )
        mock_gemini_client["get"].return_value = mock_client

        with patch("video_research_mcp.tools.research_web.asyncio.sleep", new_callable=AsyncMock):
            result = await research_web_status(interaction_id="retry-test-123")

        assert result["status"] == "in_progress"
        assert mock_client.aio.interactions.get.call_count == 2

    async def test_status_gives_up_after_3_403s(self, mock_gemini_client):
        """GIVEN 3x 403 WHEN polling THEN returns tool error."""
        mock_client = MagicMock()
        mock_client.aio.interactions.get = AsyncMock(
            side_effect=[
                RuntimeError("403 Forbidden"),
                RuntimeError("403 Forbidden"),
                RuntimeError("403 Forbidden"),
            ],
        )
        mock_gemini_client["get"].return_value = mock_client

        with patch("video_research_mcp.tools.research_web.asyncio.sleep", new_callable=AsyncMock):
            result = await research_web_status(interaction_id="give-up-test")

        assert "error" in result
        assert "403" in result["error"]

    async def test_completed_without_launch_time(self, mock_gemini_client):
        """GIVEN completed but no launch time WHEN polling THEN duration is None."""
        interaction = _make_interaction(
            interaction_id="orphan-id",
            outputs=[_make_turn([_make_text_content("Report")])],
        )
        mock_client = MagicMock()
        mock_client.aio.interactions.get = AsyncMock(return_value=interaction)
        mock_gemini_client["get"].return_value = mock_client

        _launch_times.pop("orphan-id", None)

        with patch("video_research_mcp.weaviate_store.store_deep_research", new_callable=AsyncMock):
            result = await research_web_status(interaction_id="orphan-id")

        assert result["status"] == "completed"
        assert result["duration_seconds"] is None


# ── research_web_followup ─────────────────────────────────────────────────


class TestResearchWebFollowup:
    async def test_followup_returns_response(self, mock_gemini_client):
        """GIVEN completed interaction WHEN following up THEN returns response."""
        followup_interaction = _make_interaction(
            interaction_id="followup-789",
            outputs=[_make_turn([
                _make_text_content("The key distinction is..."),
            ])],
        )
        mock_client = MagicMock()
        mock_client.aio.interactions.create = AsyncMock(return_value=followup_interaction)
        mock_gemini_client["get"].return_value = mock_client

        with patch(
            "video_research_mcp.weaviate_store.store_deep_research_followup",
            new_callable=AsyncMock,
        ) as mock_store:
            result = await research_web_followup(
                interaction_id="original-123",
                question="What about the security implications?",
            )

        assert result["interaction_id"] == "followup-789"
        assert result["previous_interaction_id"] == "original-123"
        assert "key distinction" in result["response"]
        mock_store.assert_called_once_with(
            "original-123", "followup-789",
            question="What about the security implications?",
            response="The key distinction is...",
        )

    async def test_followup_uses_previous_interaction_id(self, mock_gemini_client):
        """GIVEN interaction_id WHEN following up THEN passes previous_interaction_id."""
        followup_interaction = _make_interaction(
            interaction_id="followup-new",
            outputs=[_make_turn([_make_text_content("Answer")])],
        )
        mock_client = MagicMock()
        mock_client.aio.interactions.create = AsyncMock(return_value=followup_interaction)
        mock_gemini_client["get"].return_value = mock_client

        with patch("video_research_mcp.weaviate_store.store_deep_research_followup", new_callable=AsyncMock):
            await research_web_followup(
                interaction_id="prev-id-456",
                question="Elaborate on finding 3",
            )

        call_kwargs = mock_client.aio.interactions.create.call_args.kwargs
        assert call_kwargs["previous_interaction_id"] == "prev-id-456"
        assert call_kwargs["input"] == "Elaborate on finding 3"

    async def test_followup_error_returns_tool_error(self, mock_gemini_client):
        """GIVEN API error WHEN following up THEN returns tool error."""
        mock_client = MagicMock()
        mock_client.aio.interactions.create = AsyncMock(
            side_effect=RuntimeError("Interaction expired"),
        )
        mock_gemini_client["get"].return_value = mock_client

        result = await research_web_followup(
            interaction_id="expired-id",
            question="Follow up question",
        )

        assert "error" in result
        assert "Interaction expired" in result["error"]


# ── Model serialization ──────────────────────────────────────────────────


class TestModels:
    def test_launch_model_serializes(self):
        m = DeepResearchLaunch(interaction_id="x", status="in_progress")
        d = m.model_dump(mode="json")
        assert d["interaction_id"] == "x"
        assert d["estimated_minutes"] == "10-20"

    def test_result_model_serializes(self):
        m = DeepResearchResult(
            interaction_id="x",
            topic="test topic",
            report_text="Report",
            sources=[DeepResearchSource(url="https://a.com", title="A")],
            source_count=1,
            duration_seconds=600,
            usage={"total_tokens": 100},
        )
        d = m.model_dump(mode="json")
        assert d["source_count"] == 1
        assert d["sources"][0]["url"] == "https://a.com"

    def test_followup_model_serializes(self):
        m = DeepResearchFollowup(
            interaction_id="new",
            previous_interaction_id="old",
            response="Answer",
        )
        d = m.model_dump(mode="json")
        assert d["previous_interaction_id"] == "old"


# ── research_web_cancel ──────────────────────────────────────────────────


class TestResearchWebCancel:
    async def test_cancel_success(self, mock_gemini_client):
        """GIVEN running task WHEN cancelling THEN returns cancelled status."""
        mock_client = MagicMock()
        mock_client.aio.interactions.cancel = AsyncMock(return_value=None)
        mock_gemini_client["get"].return_value = mock_client

        _launch_times["cancel-me-123"] = {"time": time.time(), "topic": "test"}

        result = await research_web_cancel(interaction_id="cancel-me-123")

        assert result["interaction_id"] == "cancel-me-123"
        assert result["status"] == "cancelled"
        assert "cancel-me-123" not in _launch_times

    async def test_cancel_already_completed(self, mock_gemini_client):
        """GIVEN completed task WHEN cancelling THEN API error is returned."""
        mock_client = MagicMock()
        mock_client.aio.interactions.cancel = AsyncMock(
            side_effect=RuntimeError("Interaction already completed"),
        )
        mock_gemini_client["get"].return_value = mock_client

        result = await research_web_cancel(interaction_id="done-id")

        assert "error" in result
        assert "already completed" in result["error"]

    async def test_cancel_api_error(self, mock_gemini_client):
        """GIVEN API failure WHEN cancelling THEN returns tool error."""
        mock_client = MagicMock()
        mock_client.aio.interactions.cancel = AsyncMock(
            side_effect=RuntimeError("Network error"),
        )
        mock_gemini_client["get"].return_value = mock_client

        result = await research_web_cancel(interaction_id="net-err-id")

        assert "error" in result
        assert "Network error" in result["error"]


# ── _evict_stale ─────────────────────────────────────────────────────────


class TestEvictStale:
    def test_ttl_evicts_old_entries(self):
        """GIVEN entries older than TTL WHEN evicting THEN they are removed."""
        _launch_times.clear()
        now = time.time()
        _launch_times["old-1"] = {"time": now - _TTL_SECONDS - 1, "topic": "old"}
        _launch_times["old-2"] = {"time": now - _TTL_SECONDS - 100, "topic": "older"}
        _launch_times["fresh"] = {"time": now - 60, "topic": "recent"}

        _evict_stale()

        assert "old-1" not in _launch_times
        assert "old-2" not in _launch_times
        assert "fresh" in _launch_times
        _launch_times.clear()

    def test_cap_evicts_oldest_when_full(self):
        """GIVEN more than _MAX_TRACKED entries WHEN evicting THEN oldest are removed."""
        _launch_times.clear()
        now = time.time()
        for i in range(_MAX_TRACKED + 5):
            _launch_times[f"entry-{i}"] = {"time": now - i, "topic": f"topic-{i}"}

        _evict_stale()

        assert len(_launch_times) == _MAX_TRACKED
        # The 5 oldest (highest offset) should be gone
        for i in range(_MAX_TRACKED, _MAX_TRACKED + 5):
            assert f"entry-{i}" not in _launch_times
        _launch_times.clear()
