"""Mounted MCP discovery, local planning and canonical cancellation contracts."""

import hashlib
import json
from unittest.mock import patch

from fastmcp import Client

from video_research_mcp.job_store import JobStore
from video_research_mcp.server import app


def run_limits() -> dict:
    """Allow a count and generation for one requested interval."""
    return {"max_calls": 2, "max_tokens": 20000, "max_output_tokens": 100,
            "max_frames": 60, "max_windows": 2}


async def test_mounted_window_dry_run_and_validation_have_zero_provider(tmp_path, clean_config):
    """GIVEN actual MCP transport THEN discovery and planning require no inference."""
    source = tmp_path / "synthetic.mp4"
    source.write_bytes(b"synthetic declared duration; not decoded source evidence")
    request = {"file_path": str(source), "instruction": "List actions",
               "end_ms": 120000, "window_ms": 60000, "fps": 0.5}
    with patch("video_research_mcp.client.GeminiClient.get") as provider:
        async with Client(app) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert "video_analyze_windows" in tools
            assert tools["video_analyze_windows"].input_schema["properties"]["dry_run"]["default"] is True
            reply = await client.call_tool("video_analyze_windows", {
                "request": request, "execution_budget": run_limits()
            })
            result = reply.structured_content
            assert result == json.loads(reply.content[0].text)
            assert result["dry_run"] and result["provider_calls"] == result["network_calls"] == 0
            assert result["duration_verified"] is False
            assert result["source"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
            assert [(w["start_ms"], w["end_ms"]) for w in result["windows"]] == [
                (0, 60000), (60000, 120000)
            ]
            remote = await client.call_tool("video_analyze_windows", {
                "request": {key: value for key, value in request.items() if key != "file_path"}
                | {"url": "https://youtu.be/abcdefghijk"},
                "execution_budget": run_limits(),
            })
            assert remote.structured_content["source"]["sha256"] is None
            assert remote.structured_content["source"]["freshness"] == "unknown"
            assert remote.structured_content["provider_calls"] == 0
            invalid = await client.call_tool("video_analyze_windows", {
                "request": request | {"fps": True}, "execution_budget": run_limits()
            })
            assert "error" in invalid.structured_content
        provider.assert_not_called()


async def test_canonical_window_job_status_and_queued_cancel(tmp_path, monkeypatch):
    """GIVEN a queued window run THEN public cancellation prevents owner launch."""
    monkeypatch.setenv("VRM_JOB_DB", str(tmp_path / "jobs.sqlite3"))
    store = JobStore()
    row = store.create("video_windows", {"fixture": "queued"}, "owned-source", job_id="window-fixture")
    async with Client(app) as client:
        before = await client.call_tool("job_status", {"job_id": row["job_id"]})
        assert before.structured_content["kind"] == "video_windows"
        cancelled = await client.call_tool("job_cancel", {"job_id": row["job_id"]})
        assert cancelled.structured_content["status"] == "cancelled"
        assert cancelled.structured_content["provider_termination"] == "unknown"
        after = await client.call_tool("job_status", {"job_id": row["job_id"]})
        assert after.structured_content["status"] == "cancelled"
    assert store.claim(row["job_id"], "never-launch") is None
