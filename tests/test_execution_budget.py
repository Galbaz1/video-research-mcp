"""Exercise real request construction with only the external SDK mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

from google.genai import types
import pytest

from video_research_mcp.client import GeminiClient
from video_research_mcp.config import update_config
from video_research_mcp.execution_budget import ExecutionBudget, current_budget
from video_research_mcp.models.execution import ExecutionLimits


def limits(**overrides):
    """Provide a two-transmission window for counting and one generation."""
    values = dict(
        max_calls=2,
        max_tokens=2000,
        max_output_tokens=100,
        max_frames=20,
        max_windows=2,
        start_ms=0,
        end_ms=1000,
        fps=1.0,
    )
    return ExecutionLimits(**(values | overrides))


@pytest.fixture
def transport():
    """Keep concrete SDK payloads/usage and isolate only provider transport."""
    client = MagicMock()
    client.aio.models.count_tokens = AsyncMock(
        return_value=types.CountTokensResponse(total_tokens=12)
    )
    client.aio.models.generate_content = AsyncMock(
        return_value=types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(parts=[types.Part(text="answer")]))],
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=12,
                candidates_token_count=3,
                thoughts_token_count=2,
                total_token_count=17,
            ),
        )
    )
    with patch.object(GeminiClient, "get", return_value=client):
        yield client


async def test_count_and_generation_caps_usage_and_context_scope(transport):
    """GIVEN bounded execution THEN each wire call is metered and usage reconciles."""
    budget = ExecutionBudget(limits())
    with budget.activate():
        assert await GeminiClient.generate("prompt") == "answer"
        assert current_budget() is budget
    assert current_budget() is None
    cfg = transport.aio.models.generate_content.call_args.kwargs["config"]
    assert cfg.max_output_tokens == 100
    assert cfg.http_options.retry_options.attempts == 1
    count_cfg = transport.aio.models.count_tokens.call_args.kwargs["config"]
    assert count_cfg.http_options.retry_options.attempts == 1
    report = budget.report()
    assert report["provider_calls"] == 2
    assert report["requested_windows"] == report["requested_frames"] == 2
    assert report["reserved_or_reconciled_tokens"] == report["measured_total_tokens"] == 17
    assert report["usage_complete"] is True
    assert report["cost_usd"] is report["saved_tokens"] is report["observed_frames"] is None
    assert report["charge_bound_verified"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_calls": 1},
        {"max_windows": 1},
        {"max_frames": 1},
        {"max_tokens": 111},
    ],
)
async def test_prevents_second_transport_before_exceeding_limits(transport, overrides):
    """GIVEN a cap reached by count/preflight THEN generation is never sent."""
    budget = ExecutionBudget(limits(**overrides))
    with budget.activate(), pytest.raises(ValueError, match="budget exhausted"):
        await GeminiClient.generate("prompt")
    transport.aio.models.count_tokens.assert_awaited_once()
    transport.aio.models.generate_content.assert_not_awaited()
    assert budget.report()["provider_calls"] == 1


async def test_each_retry_retains_failed_reservation_and_call_bound(transport, clean_config):
    """GIVEN an ambiguous failed attempt THEN retries cannot reuse its reservation."""
    update_config(retry_base_delay=0.001, retry_max_delay=0.001, retry_max_attempts=3)
    transport.aio.models.generate_content.side_effect = RuntimeError("503 service unavailable")
    budget = ExecutionBudget(limits(max_calls=3, max_windows=3))
    with budget.activate(), pytest.raises(ValueError, match="provider call limit"):
        await GeminiClient.generate("prompt")
    assert transport.aio.models.generate_content.await_count == 2
    assert budget.report()["reserved_or_reconciled_tokens"] == 224
    assert budget.report()["measured_total_tokens"] is None
    assert all(r["status"] == "failed_usage_unknown" for r in budget.calls[1:])


@pytest.mark.parametrize("count", [None, -1])
async def test_unknown_token_count_blocks_generation(transport, count):
    transport.aio.models.count_tokens.return_value = types.CountTokensResponse(total_tokens=count)
    with ExecutionBudget(limits()).activate(), pytest.raises(ValueError, match="unknown"):
        await GeminiClient.generate("prompt")
    transport.aio.models.generate_content.assert_not_awaited()


async def test_missing_usage_keeps_full_conservative_reservation(transport):
    transport.aio.models.generate_content.return_value.usage_metadata = None
    budget = ExecutionBudget(limits())
    with budget.activate():
        await GeminiClient.generate("prompt")
    assert budget.report()["reserved_or_reconciled_tokens"] == 112
    assert budget.report()["usage_complete"] is False
    assert budget.report()["measured_total_tokens"] is None


async def test_provider_truncation_is_retained_separately_from_pagination(transport):
    transport.aio.models.generate_content.return_value.candidates[
        0
    ].finish_reason = types.FinishReason.MAX_TOKENS
    budget = ExecutionBudget(limits())
    with budget.activate():
        await GeminiClient.generate("prompt")
    assert budget.report()["generation_truncated"] is True
    assert budget.calls[-1]["finish_reasons"] == ["MAX_TOKENS"]


async def test_provider_overrun_blocks_further_operations(transport):
    transport.aio.models.generate_content.return_value.usage_metadata.total_token_count = 150
    budget = ExecutionBudget(limits(max_calls=4, max_windows=4))
    with budget.activate():
        await GeminiClient.generate("prompt")
        with pytest.raises(ValueError, match="budget exhausted"):
            await GeminiClient.generate("other")
    assert budget.report()["provider_exceeded_reservation"] is True
    assert budget.report()["measured_total_tokens"] == 150
    assert transport.aio.models.count_tokens.await_count == 1


async def test_unmetered_context_fails_before_network(transport):
    with ExecutionBudget(limits()).activate(), pytest.raises(ValueError, match="cannot count"):
        await GeminiClient.generate("prompt", system_instruction="extra context")
    transport.aio.models.count_tokens.assert_not_awaited()
    transport.aio.models.generate_content.assert_not_awaited()


@pytest.mark.parametrize(
    "values",
    [
        {"max_calls": True},
        {"start_ms": 1.2},
        {"fps": True},
        {"fps": float("nan")},
        {"end_ms": 0},
        {"start_ms": 1000},
        {"max_frames": 0},
        {"max_windows": 0},
    ],
)
def test_invalid_limits_fail_at_boundary(values):
    with pytest.raises(ValueError):
        limits(**values)
