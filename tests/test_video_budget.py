"""Public video-tool budget and response-view journeys with mocked inference."""

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

from google.genai import types
import pytest

from video_research_mcp.client import GeminiClient
from video_research_mcp.models.execution import ExecutionLimits
from video_research_mcp.tools.video import video_analyze
from video_research_mcp.tools.video_plan import bounded_contents, plan_video

URL = "https://youtu.be/abcdefghijk"
SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "transcript": {"type": "string"},
        "citations": {"type": "array"},
        "large_field": {"type": "string"},
    },
}


def budget(**overrides):
    """Budget both the count and generation transmission of a one-second window."""
    return (
        dict(
            max_calls=2,
            max_tokens=2000,
            max_output_tokens=100,
            max_frames=2,
            max_windows=2,
            start_ms=0,
            end_ms=1000,
            fps=1.0,
        )
        | overrides
    )


@pytest.fixture
def sdk_transport(clean_config):
    """Use real request/client/core logic and replace only the external SDK."""
    data = {
        "summary": "draft",
        "transcript": "αβ🙂XYZ",
        "citations": [{"source_id": "original", "passage_id": "p1", "text": "αβ🙂XYZ"}],
        "large_field": "x" * 20000,
    }
    client = MagicMock()
    client.aio.models.count_tokens = AsyncMock(
        return_value=types.CountTokensResponse(total_tokens=12)
    )
    client.aio.models.generate_content = AsyncMock(
        return_value=types.GenerateContentResponse(
            candidates=[
                types.Candidate(content=types.Content(parts=[types.Part(text=json.dumps(data))]))
            ],
            usage_metadata=types.GenerateContentResponseUsageMetadata(total_token_count=40),
        )
    )
    with (
        patch.object(GeminiClient, "get", return_value=client),
        patch(
            "video_research_mcp.tools.video._youtube_metadata_pipeline", new_callable=AsyncMock
        ) as optimizer,
        patch("video_research_mcp.tools.video.prewarm_cache") as prewarm,
    ):
        yield client, optimizer, prewarm, data


@pytest.mark.parametrize("local", [True, False])
async def test_dry_plan_hashes_local_or_enumerates_remote_with_zero_calls(
    tmp_path, sdk_transport, local
):
    """GIVEN a plan request THEN no provider, upload, optimizer or prewarm runs."""
    client, optimizer, prewarm, _ = sdk_transport
    path = tmp_path / "owned.mp4"
    path.write_bytes(b"mocked-provider-owned-fixture")
    params = {"file_path": str(path)} if local else {"url": URL}
    result = await video_analyze(**params, dry_run=True, execution_budget=budget())
    assert result["provider_calls"] == result["network_calls"] == 0
    source = result["remote_payloads"][0]["source"]
    if local:
        assert source["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert result["local_reads"][0]["bytes"] == path.stat().st_size
    else:
        assert source["freshness"] == "unknown" and source["sha256"] is None
        assert source["uri"] == "https://www.youtube.com/watch?v=abcdefghijk"
        assert result["local_reads"] == []
    client.aio.models.count_tokens.assert_not_awaited()
    client.aio.models.generate_content.assert_not_awaited()
    client.aio.files.upload.assert_not_called()
    optimizer.assert_not_awaited()
    prewarm.assert_not_called()


async def test_bounded_real_caller_projects_after_complete_result(sdk_transport):
    """GIVEN a bounded custom result THEN source/citations/usage survive sparse pagination."""
    client, optimizer, prewarm, data = sdk_transport
    result = await video_analyze(
        url=URL,
        execution_budget=budget(),
        output_schema=SCHEMA,
        output_fields=["summary"],
        transcript_offset=2,
        transcript_limit=2,
    )
    assert "error" not in result
    assert result["transcript"] == "🙂X"
    assert result["transcript_page"]["next_offset"] == 4
    assert result["transcript_page"]["prefix_omitted"] == 2
    assert result["transcript_page"]["remaining"] == 2
    assert result["citations"] == data["citations"] and "large_field" not in result
    assert result["source_freshness"] == "unknown"
    assert result["source_sha256"] is result["source_revision"] is None
    assert result["execution_usage"]["measured_total_tokens"] == 40
    contents = client.aio.models.generate_content.call_args.kwargs["contents"]
    media = contents.parts[0]
    assert media.media_processing == types.MediaProcessing.STATIC
    assert media.video_metadata.model_dump(exclude_none=True) == {
        "fps": 1.0,
        "start_offset": "0.000s",
        "end_offset": "1.000s",
    }
    assert media.file_data.file_uri == "https://www.youtube.com/watch?v=abcdefghijk"
    optimizer.assert_not_awaited()
    prewarm.assert_not_called()


async def test_budget_failure_retains_attempts_and_unknown_usage(sdk_transport):
    client, _, _, _ = sdk_transport
    result = await video_analyze(
        url=URL, execution_budget=budget(max_calls=1), output_schema=SCHEMA
    )
    assert "budget exhausted" in result["error"]
    assert result["execution_usage"]["provider_calls"] == 0
    assert result["execution_usage"]["measured_total_tokens"] is None
    client.aio.models.generate_content.assert_not_awaited()


async def test_projection_failure_keeps_usage_after_inference(sdk_transport):
    result = await video_analyze(
        url=URL, execution_budget=budget(), output_schema=SCHEMA, output_fields=["missing"]
    )
    assert "Selected fields" in result["error"]
    assert result["execution_usage"]["measured_total_tokens"] == 40


@pytest.mark.parametrize(
    "params",
    [
        {"transcript_offset": True},
        {"transcript_offset": 2},
        {"transcript_limit": 0},
        {"output_fields": [""]},
        {"execution_budget": budget(max_frames=0)},
        {"execution_budget": budget(fps=True)},
    ],
)
async def test_invalid_options_fail_before_provider(sdk_transport, params):
    client, optimizer, prewarm, _ = sdk_transport
    result = await video_analyze(url=URL, **params)
    assert "error" in result
    client.aio.models.count_tokens.assert_not_awaited()
    client.aio.models.generate_content.assert_not_awaited()
    optimizer.assert_not_awaited()
    prewarm.assert_not_called()


def test_local_source_change_after_plan_fails_before_send(tmp_path):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"original")
    limits = ExecutionLimits(**budget())
    plan = plan_video(
        url=None, file_path=str(path), instruction="summary", limits=limits, strict_contract=False
    )
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed after planning"):
        bounded_contents(plan, "summary", limits)


async def test_unsupported_upload_and_strict_modes_are_concrete_plan_blockers(
    tmp_path, sdk_transport
):
    client, _, _, _ = sdk_transport
    path = tmp_path / "large.mp4"
    with path.open("wb") as stream:
        stream.truncate(20 * 1024 * 1024)
    planned = await video_analyze(file_path=str(path), dry_run=True, execution_budget=budget())
    assert len(planned["launch_blockers"]) == 1
    result = await video_analyze(file_path=str(path), execution_budget=budget())
    assert "File API threshold" in result["error"]
    strict = await video_analyze(url=URL, execution_budget=budget(), strict_contract=True)
    assert "strict artifacts require a separate plan" in strict["error"]
    client.aio.models.count_tokens.assert_not_awaited()
    client.aio.models.generate_content.assert_not_awaited()
