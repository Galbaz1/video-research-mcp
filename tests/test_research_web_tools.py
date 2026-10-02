"""Tests for Deep Research (Interactions API) tools."""

from __future__ import annotations

import time
import asyncio
import sqlite3
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import interactions

from video_research_mcp.job_store import JobStore
from video_research_mcp.research_jobs import account_scope, find_operation

from video_research_mcp.models.research_web import (
    DeepResearchFollowup,
    DeepResearchLaunch,
    DeepResearchResult,
    DeepResearchSource,
)
from video_research_mcp.tools.research_web import (
    _extract_report,
    _extract_usage,
    research_web,
    research_web_cancel,
    research_web_followup,
    research_web_status,
)


@pytest.fixture(autouse=True)
def _isolated_jobs(tmp_path, monkeypatch):
    """Use owned durable state and disable optional services for these SDK mocks."""
    monkeypatch.setenv("VRM_JOB_DB", str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setenv("WEAVIATE_URL", "")
    monkeypatch.setenv("WEAVIATE_API_KEY", "")


def _seed_operation(interaction_id, metadata):
    store = JobStore()
    job = store.create(
        "research_web",
        {
            "topic": metadata["topic"],
            "account_scope": account_scope(),
        },
        "fixture-source",
        job_id=interaction_id,
        exclusive_key="fixture:" + interaction_id,
    )
    store.claim(job["job_id"], "fixture")
    store.checkpoint(
        job["job_id"],
        "fixture",
        status="running",
        external_id=interaction_id,
        result={"interaction_id": interaction_id, "status": "in_progress"},
        release=True,
    )
    with sqlite3.connect(os.environ["VRM_JOB_DB"]) as connection:
        connection.execute(
            "UPDATE jobs SET created_at=? WHERE job_id=?", (metadata["time"], interaction_id)
        )


def _make_interaction(
    interaction_id: str = "test-interaction-123",
    status: str = "completed",
    steps: list | None = None,
    usage: object | None = None,
):
    """Build a concrete current-SDK Interaction, with no legacy outputs field."""
    return interactions.Interaction(id=interaction_id, status=status, steps=steps, usage=usage)


def _make_text_content(text: str):
    return interactions.TextContent(text=text)


def _make_search_result_content(url: str, title: str = ""):
    return interactions.TextContent(
        text="",
        annotations=[
            interactions.URLCitation(url=url, title=title),
        ],
    )


def _make_turn(contents: list):
    return interactions.ModelOutputStep(content=contents)


def _make_usage(input_tokens=100, output_tokens=200, total=300, thought=50):
    return interactions.Usage(
        total_input_tokens=input_tokens,
        total_output_tokens=output_tokens,
        total_tokens=total,
        total_thought_tokens=thought,
    )


class TestExtractReport:
    def test_extracts_text_citations_and_url_context(self):
        """GIVEN current SDK steps WHEN extracting THEN unique sources and final text survive."""
        interaction = _make_interaction(
            steps=[
                interactions.URLContextResultStep(
                    call_id="url-1",
                    result=[
                        interactions.URLContextResult(url="https://other.com", status="success"),
                    ],
                ),
                interactions.GoogleSearchResultStep(
                    call_id="search-1",
                    result=[
                        interactions.GoogleSearchResult(search_suggestions="Search suggestions"),
                    ],
                ),
                _make_turn(
                    [
                        _make_text_content("# Report Title\n\n"),
                        _make_search_result_content("https://example.com", "Example"),
                        _make_text_content("## Section 1"),
                        _make_search_result_content("https://example.com", "Example"),
                    ]
                ),
            ]
        )
        text, sources = _extract_report(interaction)

        assert text == "# Report Title\n\n## Section 1"
        assert len(sources) == 2
        assert sources[0].url == "https://other.com"
        assert sources[0].status == "success"
        assert sources[1].title == "Example"

    @pytest.mark.parametrize("steps", [None, []])
    def test_empty_steps(self, steps):
        assert _extract_report(_make_interaction(steps=steps)) == ("", [])

    @pytest.mark.parametrize(
        "boundary",
        [
            interactions.ThoughtStep(summary=[_make_text_content("Private summary")]),
            interactions.GoogleSearchResultStep(call_id="search-boundary", result=[]),
        ],
    )
    def test_final_model_output_excludes_thoughts_user_input_and_earlier_outputs(self, boundary):
        interaction = _make_interaction(
            steps=[
                interactions.UserInputStep(content=[_make_text_content("User prompt")]),
                _make_turn([_make_text_content("Intermediate analysis")]),
                boundary,
                _make_turn([_make_text_content("Final report")]),
            ]
        )
        text, _ = _extract_report(interaction)
        assert text == "Final report"

    def test_consecutive_final_outputs_are_preserved_exactly(self):
        """GIVEN a split final answer WHEN extracting THEN all trailing output text survives."""
        interaction = _make_interaction(
            steps=[
                _make_turn([_make_text_content("First half. ")]),
                _make_turn([_make_text_content("Second half.")]),
            ]
        )
        assert interaction.output_text == "First half. Second half."
        assert _extract_report(interaction) == ("First half. Second half.", [])


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
    async def test_concurrent_launches_make_only_one_billable_request(self, mock_gemini_client):
        """GIVEN overlapping launches WHEN transport yields THEN local guard stays atomic."""
        started = asyncio.Event()
        release = asyncio.Event()

        async def create(**kwargs):
            started.set()
            await release.wait()
            return _make_interaction(interaction_id="one-launch", status="queued")

        client = MagicMock()
        client.aio.interactions.create = AsyncMock(side_effect=create)
        mock_gemini_client["get"].return_value = client
        first = asyncio.create_task(research_web("First detailed research brief"))
        await started.wait()
        second = asyncio.create_task(research_web("Second detailed research brief"))
        release.set()
        first_result, second_result = await asyncio.gather(first, second)
        assert first_result["interaction_id"] == "one-launch"
        assert "already in progress" in second_result["error"]
        assert client.aio.interactions.create.await_count == 1

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
        job = find_operation("dr-abc-123")
        assert job["created_at"] > 0
        assert job["request"]["topic"] == "Impact of quantum computing on cryptography in 2026"
        assert result["job_receipt"]["request_sha256"] == job["request_sha256"]
        request = mock_client.aio.interactions.create.call_args.kwargs
        assert request["store"] is True
        assert request["background"] is True

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

    async def test_launch_uses_configured_agent(
        self, mock_gemini_client, clean_config, monkeypatch
    ):
        """GIVEN custom agent env var WHEN launching THEN uses configured agent."""
        monkeypatch.setenv("DEEP_RESEARCH_AGENT", "custom-agent-v2")
        mock_interaction = _make_interaction(interaction_id="dr-custom", status="in_progress")
        mock_client = MagicMock()
        mock_client.aio.interactions.create = AsyncMock(return_value=mock_interaction)
        mock_gemini_client["get"].return_value = mock_client

        await research_web(topic="Test topic for agent config verification")

        call_kwargs = mock_client.aio.interactions.create.call_args.kwargs
        assert call_kwargs["agent"] == "custom-agent-v2"

    async def test_launch_blocked_when_active_task(self, mock_gemini_client):
        """GIVEN active interaction <30 min old WHEN launching THEN returns error."""
        _seed_operation("active-task-1", {"time": time.time() - 300, "topic": "active"})

        result = await research_web(topic="New topic that should be blocked by guard")

        assert "error" in result
        assert "already in progress" in result["error"]
        assert "active-task-1" in result["error"]

    async def test_stale_remote_task_still_blocks_new_billable_launch(self, mock_gemini_client):
        """GIVEN an old remote task THEN age alone never supplies resend authority."""
        _seed_operation("stale-task-1", {"time": time.time() - 7201, "topic": "stale"})
        result = await research_web(topic="New launch must not duplicate uncertain remote work")
        assert "already in progress" in result["error"]
        assert find_operation("stale-task-1")["status"] == "running"

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
    @pytest.mark.parametrize("status", ["queued", "in_progress"])
    async def test_active_status_keeps_launch_guard(self, status, mock_gemini_client):
        interaction = _make_interaction(interaction_id="active", status=status)
        mock_client = MagicMock()
        mock_client.aio.interactions.get = AsyncMock(return_value=interaction)
        mock_gemini_client["get"].return_value = mock_client
        _seed_operation("active", {"time": time.time(), "topic": "Research brief"})
        result = await research_web_status("active")
        assert result["status"] == status
        assert find_operation("active")["status"] == "running"

    @pytest.mark.parametrize("status", ["failed", "cancelled", "incomplete", "requires_action"])
    async def test_terminal_status_releases_guard_and_returns_sdk_errors(
        self, status, mock_gemini_client
    ):
        interaction = interactions.Interaction(
            id="terminal",
            status=status,
            errors=[interactions.Error(code="test", message="Provider result")],
        )
        mock_client = MagicMock()
        mock_client.aio.interactions.get = AsyncMock(return_value=interaction)
        mock_gemini_client["get"].return_value = mock_client
        _seed_operation("terminal", {"time": time.time(), "topic": "Research brief"})
        result = await research_web_status("terminal")
        assert result["status"] == status
        assert result["errors"][0]["message"] == "Provider result"
        expected = {
            "failed": "failed",
            "cancelled": "cancelled",
            "incomplete": "partial",
            "requires_action": "unknown",
        }[status]
        assert find_operation("terminal")["status"] == expected

    async def test_completed_returns_full_report(self, mock_gemini_client):
        """GIVEN completed interaction WHEN polling THEN returns report with sources."""
        interaction = _make_interaction(
            steps=[
                _make_turn(
                    [
                        _make_text_content("# Deep Research Report\n\n"),
                        _make_search_result_content("https://source1.com", "Source 1"),
                    ]
                ),
                _make_turn(
                    [
                        _make_text_content("Findings here."),
                        _make_search_result_content("https://source2.com", "Source 2"),
                    ]
                ),
            ],
            usage=_make_usage(500, 8000, 8500, 200),
        )
        mock_client = MagicMock()
        mock_client.aio.interactions.get = AsyncMock(return_value=interaction)
        mock_gemini_client["get"].return_value = mock_client

        _seed_operation("test-interaction-123", {"time": time.time() - 600, "topic": "test topic"})

        with patch(
            "video_research_mcp.weaviate_store.store_deep_research", new_callable=AsyncMock
        ) as mock_store:
            mock_store.return_value = "uuid-1"
            result = await research_web_status(interaction_id="test-interaction-123")

        assert result["status"] == "completed"
        assert result["report_text"] == "# Deep Research Report\n\nFindings here."
        assert mock_store.call_args.args[0]["report_text"] == result["report_text"]
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
        interaction = _make_interaction(interaction_id="retry-test-123", status="in_progress")
        mock_client = MagicMock()
        mock_client.aio.interactions.get = AsyncMock(
            side_effect=[RuntimeError("403 Forbidden"), interaction],
        )
        mock_gemini_client["get"].return_value = mock_client

        with patch("video_research_mcp.research_poll.asyncio.sleep", new_callable=AsyncMock):
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

        with patch("video_research_mcp.research_poll.asyncio.sleep", new_callable=AsyncMock):
            result = await research_web_status(interaction_id="give-up-test")

        assert "error" in result
        assert "403" in result["error"]

    async def test_completed_without_launch_time(self, mock_gemini_client):
        """GIVEN completed but no launch time WHEN polling THEN duration is None."""
        interaction = _make_interaction(
            interaction_id="orphan-id",
            steps=[_make_turn([_make_text_content("Report")])],
        )
        mock_client = MagicMock()
        mock_client.aio.interactions.get = AsyncMock(return_value=interaction)
        mock_gemini_client["get"].return_value = mock_client

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
            steps=[
                _make_turn(
                    [
                        _make_text_content("The key distinction "),
                    ]
                ),
                _make_turn(
                    [
                        _make_text_content("is..."),
                    ]
                ),
            ],
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
            "original-123",
            "followup-789",
            question="What about the security implications?",
            response="The key distinction is...",
        )

    async def test_followup_uses_previous_interaction_id(self, mock_gemini_client):
        """GIVEN interaction_id WHEN following up THEN passes previous_interaction_id."""
        followup_interaction = _make_interaction(
            interaction_id="followup-new",
            steps=[_make_turn([_make_text_content("Answer")])],
        )
        mock_client = MagicMock()
        mock_client.aio.interactions.create = AsyncMock(return_value=followup_interaction)
        mock_gemini_client["get"].return_value = mock_client

        with patch(
            "video_research_mcp.weaviate_store.store_deep_research_followup", new_callable=AsyncMock
        ):
            await research_web_followup(
                interaction_id="prev-id-456",
                question="Elaborate on finding 3",
            )

        call_kwargs = mock_client.aio.interactions.create.call_args.kwargs
        assert call_kwargs["previous_interaction_id"] == "prev-id-456"
        assert call_kwargs["input"] == "Elaborate on finding 3"
        assert call_kwargs["generation_config"]["thinking_level"] == "medium"

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
        mock_client.aio.interactions.cancel = AsyncMock(
            return_value=_make_interaction(interaction_id="cancel-me-123", status="cancelled")
        )
        mock_gemini_client["get"].return_value = mock_client

        _seed_operation("cancel-me-123", {"time": time.time(), "topic": "test"})

        result = await research_web_cancel(interaction_id="cancel-me-123")

        assert result["interaction_id"] == "cancel-me-123"
        assert result["status"] == "cancelled"
        assert find_operation("cancel-me-123")["status"] == "cancelled"

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


class TestDurableRetention:
    def test_age_and_old_registry_cap_never_discard_recovery_evidence(self):
        """GIVEN more than the old cap THEN fresh process lookup retains every operation."""
        for i in range(105):
            _seed_operation(f"entry-{i}", {"time": time.time() - 8000 - i, "topic": f"topic-{i}"})
        assert len(JobStore().list_active("research_web")) == 105
        assert find_operation("entry-104")["request"]["topic"] == "topic-104"
