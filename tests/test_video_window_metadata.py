"""Public local-window requests and exact normalized cache contracts."""

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

from google.genai import types
import pytest

from video_research_mcp.client import GeminiClient
from video_research_mcp.config import update_config
from video_research_mcp.tools.video import video_analyze
from video_research_mcp.video_window_metadata import normalize_window

SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}}


@pytest.fixture
def transport(tmp_path, clean_config, mock_weaviate_disabled):
    """Replace only external SDK inference and retain real preparation/cache paths."""
    update_config(cache_dir=str(tmp_path / "cache"))
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(
        return_value=types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(parts=[types.Part(
                text=json.dumps({"summary": "provider fixture"})
            )]))]
        )
    )
    with (
        patch.object(GeminiClient, "get", return_value=client),
        patch("video_research_mcp.tools.video.prewarm_cache") as prewarm,
    ):
        yield client, prewarm


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [("27m", "28m", "1620.000s"), ("1h2m3.125s", "2h", "3723.125s"),
     (None, "0.001s", "0.000s")],
)
def test_ordered_durations_normalize_to_milliseconds(start, end, expected):
    metadata = normalize_window(0.5, start, end)
    assert metadata.start_offset == expected and metadata.fps == 0.5
    assert normalize_window(None, None, None) is None


@pytest.mark.parametrize("values", [
    (True, None, None), (float("nan"), None, None), (float("inf"), None, None),
    (0, None, None), (31, None, None), (1, "-1s", "2s"), (1, "1s", "1s"),
    (1, "2s", "1s"), (1, "NaNs", None), (1, "1s2m", None),
    (1, "", None), (1, "0.0001s", None), (1, "1" * 65 + "s", None),
])
def test_invalid_window_values_are_rejected(values):
    with pytest.raises(ValueError):
        normalize_window(*values)


async def test_actual_sdk_metadata_normalized_cache_and_original_timebase(tmp_path, transport):
    """GIVEN equivalent and changed windows THEN exact SDK semantics control cache reuse."""
    client, prewarm = transport
    source = tmp_path / "owned.mp4"
    source.write_bytes(b"owned SDK fixture; no factual inference")
    args = {"file_path": str(source), "output_schema": SCHEMA, "fps": 0.5}
    first = await video_analyze(**args, start_offset="1m", end_offset="61s",
                                output_fields=["summary"])
    alias = await video_analyze(**args, start_offset="60s", end_offset="1m1s")
    changed = await video_analyze(**args, start_offset="61s", end_offset="62s")
    dense = await video_analyze(**(args | {"fps": 1.0}), start_offset="1m", end_offset="61s")
    assert all("error" not in result for result in (first, alias, changed, dense))
    assert alias["cached"] is True
    assert client.aio.models.generate_content.await_count == 3
    content = client.aio.models.generate_content.call_args_list[0].kwargs["contents"]
    media = content.parts[0]
    assert media.inline_data.data == source.read_bytes()
    assert media.media_processing == types.MediaProcessing.STATIC
    assert media.video_metadata.model_dump(exclude_none=True) == {
        "fps": 0.5, "start_offset": "60.000s", "end_offset": "61.000s"
    }
    assert "do not reset the window start to zero" in content.parts[1].text
    assert first["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert first["analysis_window"]["observed_coverage"] == "unknown"
    assert first["analysis_window"]["watched_intervals"] == []
    prewarm.assert_not_called()


async def test_plain_window_dry_plan_exposes_full_payload_and_no_provider(tmp_path, transport):
    client, prewarm = transport
    source = tmp_path / "owned.mp4"
    source.write_bytes(b"owned planning fixture")
    result = await video_analyze(file_path=str(source), dry_run=True, fps=0.5,
                                 start_offset="1m", end_offset="2m")
    assert result["provider_calls"] == result["network_calls"] == 0
    payload = result["remote_payloads"][0]
    assert payload["source"]["bytes"] == source.stat().st_size
    assert payload["video_metadata"]["start_offset"] == "60.000s"
    assert result["analysis_window"]["observed_coverage"] == "unknown"
    client.aio.models.generate_content.assert_not_awaited()
    prewarm.assert_not_called()


@pytest.mark.parametrize("options", [
    {"url": "https://youtu.be/abcdefghijk", "fps": 1},
    {"file_path": "/not-read.mp4", "fps": 1, "execution_budget": {}},
    {"file_path": "/not-read.mp4", "start_offset": "2s", "end_offset": "1s"},
])
async def test_public_invalid_options_stop_before_source_or_sdk(transport, options):
    client, _ = transport
    result = await video_analyze(**options)
    assert "error" in result
    client.aio.models.generate_content.assert_not_awaited()
    client.aio.files.upload.assert_not_called()
