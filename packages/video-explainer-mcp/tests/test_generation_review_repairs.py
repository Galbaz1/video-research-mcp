"""Exercise actual admission, resume and logging boundaries found in review."""

import importlib
import subprocess
import sys

import httpx
import pytest

from tests import test_generation_adapters as fixtures
from video_explainer_mcp import config, generation as service
from video_explainer_mcp import generation_assets as assets
from video_explainer_mcp.tools.generation import explainer_generation_poll, explainer_generation_submit

wire = fixtures.wire


async def test_submit_origin_changes_during_quote_read_refuse_dispatch(wire, monkeypatch):
    original = service.read_operator_quote

    def change_origin(*args):
        result = original(*args)
        config._config.dashscope_base_url = fixtures.BASE.replace("fixture.", "other.")
        return result

    monkeypatch.setattr(service, "read_operator_quote", change_origin)
    result = await explainer_generation_submit("fixture", fixtures.request(wire))
    assert result["status"] == "unknown" and result["state"]["submit_count"] == 1
    assert not wire[1] and result["provider_operation_id"] is None
    assert (await explainer_generation_submit("fixture", fixtures.request(wire)))["job_id"] == result["job_id"]
    assert not wire[1]


@pytest.mark.parametrize("action", ["poll", "cancel"])
async def test_redeploy_blocks_new_effect_and_keeps_frozen_job(wire, monkeypatch, action):
    first = await fixtures.start(wire)
    revisions = service.adapter_revisions()
    monkeypatch.setattr(service, "adapter_revisions", lambda: {**revisions, "generation.py": "0" * 64})
    function = service.poll_generation if action == "poll" else service.cancel_generation
    with pytest.raises(ValueError, match="adapter changed"):
        await function(first["job_id"], fixtures.operation("new-effect"))
    assert len(wire[1]) == 1
    importlib.reload(service)
    replay = await explainer_generation_submit("fixture", fixtures.request(wire))
    assert replay["job_id"] == first["job_id"] and len(wire[1]) == 1


async def test_missing_decoder_refuses_before_job_or_provider_effect(wire, monkeypatch):
    def missing():
        raise FileNotFoundError("FFmpeg is unavailable")

    monkeypatch.setattr(service, "executable_identity", missing)
    result = await explainer_generation_submit("fixture", fixtures.request(wire))
    assert "FFmpeg is unavailable" in result["error"] and not wire[1]


async def test_completed_oversized_replacement_never_fetches_provider(wire, monkeypatch):
    async def qualify(artifact, request):
        return {"full_decode": True, "artifact_sha256": artifact["sha256"]}

    monkeypatch.setattr(service, "qualify_asset", qualify)
    first = await fixtures.start(wire)
    wire[2].extend([fixtures.task("SUCCEEDED", video_url=fixtures.URL), httpx.Response(200, content=b"fixture")])
    completed = await explainer_generation_poll(first["job_id"], fixtures.operation("complete"))
    assert completed["status"] == "completed"
    with open(completed["state"]["asset"]["path"], "wb") as stream:
        stream.truncate(assets.MAX_ASSET_BYTES + 1)
    changed = await explainer_generation_poll(first["job_id"], fixtures.operation("changed"))
    assert changed["status"] == "unknown" and len(wire[1]) == 3
    assert changed["artifact_hashes"] == completed["artifact_hashes"]


async def test_controller_deadline_expires_before_operation(wire, monkeypatch):
    first = await fixtures.start(wire)
    store = service._store()
    import time
    monkeypatch.setattr(service.time, "monotonic", lambda: time.time() + 1000000)
    with pytest.raises(TimeoutError, match="readback deadline"):
        store.get(first["job_id"])
    assert len(wire[1]) == 1


def test_default_companion_startup_suppresses_signed_url_info_logs():
    code = '''import asyncio,logging,httpx
logging.basicConfig(level=logging.INFO)
from video_explainer_mcp.server import app
from video_explainer_mcp import generation_assets as assets
async def handle(request): return httpx.Response(200,content=b"x")
assets.http_client=lambda:httpx.AsyncClient(transport=httpx.MockTransport(handle))
assert logging.getLogger("httpx").level>=logging.WARNING
asyncio.run(assets.request_bytes("GET","https://dashscope-result-sh.oss-accelerate.aliyuncs.com/a.mp4?Signature=SIGNED_FIXTURE_SECRET",{},None,8))
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SIGNED_FIXTURE_SECRET" not in result.stdout + result.stderr
