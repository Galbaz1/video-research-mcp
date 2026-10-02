"""Public MCP image schemas, delivery and retained source/artifact readback."""

import base64
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

from fastmcp import Client
from jsonschema import validate
from PIL import Image
import pytest
from pydantic import ValidationError

from video_research_mcp.models.image_edit import ImageEditRequest
from video_research_mcp.tools.image import image_server


@pytest.fixture(autouse=True)
def private_config(tmp_path, monkeypatch, clean_config):
    """Confine public tool outputs and policy to this test's temporary workspace."""
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))


@pytest.mark.parametrize("invalid_input", [
    {"max_pixels": True},
    {"time_seconds": -1},
    {"crop": {"space": "pixel", "coordinates": [0, 0, 1.5, 1]}},
    {"crop": {"space": "normalized1000", "coordinates": [False, 0, 500, 500]}},
    {"annotations": [{"kind": "circle", "coordinates": [0, 0, float("nan"), 5]}]},
    {"cutout": {"method": "polygon", "rings": []}},
    {"unexpected_option": "ignored"},
])
async def test_invalid_edit_request_rejected_before_source_open(invalid_input, monkeypatch):
    """GIVEN invalid boundary input WHEN called THEN no engine/decode begins."""
    engine = AsyncMock()
    monkeypatch.setattr("video_research_mcp.image_edit.edit_image", engine)
    async with Client(image_server) as client:
        reply = await client.call_tool("image_edit", {"request": {"file_path": "/unused.png", **invalid_input}},
                                       raise_on_error=False)
    assert reply.is_error
    engine.assert_not_awaited()


@pytest.mark.parametrize("value", [float("inf"), float("nan"), True])
def test_nonfinite_video_point_is_rejected_by_model(value):
    """Nonfinite floats have no JSON representation; validate before serialization."""
    with pytest.raises(ValidationError):
        ImageEditRequest(file_path="/unused.png", time_seconds=value)


async def test_public_crop_native_text_and_digest_readback(tmp_path):
    source = tmp_path / "original.png"
    original = Image.new("RGBA", (12, 8), (10, 20, 30, 128))
    original.putpixel((4, 3), (255, 0, 0, 255))
    original.save(source)
    original_bytes = source.read_bytes()
    args = {"request": {"file_path": str(source), "crop": {"space": "pixel", "coordinates": [3, 2, 4, 4]}}}
    async with Client(image_server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert set(tools) == {"image_edit", "image_manifest_read", "image_ocr", "video_clip_export"}
        for tool in tools.values():
            assert tool.annotations.open_world_hint is False and tool.annotations.destructive_hint is False
        reply = await client.call_tool("image_edit", args)
        value = reply.structured_content
        validate(value, tools["image_edit"].output_schema)
        assert json.loads(reply.content[0].text) == value and reply.content[1].type == "image"
        metadata = value["metadata"]
        assert hashlib.sha256(base64.b64decode(reply.content[1].data)).hexdigest() == metadata["artifact"]["sha256"]
        with Image.open(metadata["artifact"]["path"]) as image:
            assert image.size == (4, 4) and image.getpixel((1, 1)) == (255, 0, 0, 255)
        manifest = metadata["manifest"]
        restored = await client.call_tool("image_manifest_read", {
            "manifest_path": manifest["path"], "expected_sha256": manifest["sha256"],
        })
        assert restored.structured_content["verified"] is True
        assert len(restored.content) == 1
        assert restored.structured_content["manifest"]["artifact"] == metadata["artifact"]
        validate(restored.structured_content, tools["image_manifest_read"].output_schema)
        Path(metadata["artifact"]["path"]).write_bytes(b"changed after export")
        denied = await client.call_tool("image_manifest_read", {
            "manifest_path": manifest["path"], "expected_sha256": manifest["sha256"],
        }, raise_on_error=False)
        assert denied.is_error and "error" in denied.structured_content
    assert source.read_bytes() == original_bytes


async def test_optional_ocr_dependency_has_actionable_structured_error(monkeypatch):
    engine = AsyncMock(side_effect=ImportError("Tesseract is unavailable; install it separately"))
    monkeypatch.setattr("video_research_mcp.image_ocr.recognize_image", engine)
    async with Client(image_server) as client:
        reply = await client.call_tool("image_ocr", {"request": {"file_path": "/unused.png", "engine": "tesseract"}})
    assert reply.structured_content["category"] == "DEPENDENCY_MISSING"
    assert reply.structured_content["retryable"] is False
    assert "Tesseract" in reply.structured_content["hint"]


@pytest.mark.parametrize("canceled", [False, True])
async def test_public_ocr_failure_cleans_preparation_and_preserves_prior_export(
    tmp_path, monkeypatch, canceled
):
    """A backend failure/cancel leaves no unreturned image or OCR slot."""
    import asyncio

    source = tmp_path / "owned.png"
    Image.new("RGB", (32, 20), "white").save(source)
    original = source.read_bytes()
    entered, finished = asyncio.Event(), asyncio.Event()

    async def stopped_backend(*args):
        entered.set()
        try:
            if canceled:
                await asyncio.Future()
            raise RuntimeError("controlled OCR backend failure")
        finally:
            finished.set()

    monkeypatch.setattr("video_research_mcp.image_ocr.run_vision", stopped_backend)
    async with Client(image_server) as client:
        earlier = await client.call_tool("image_edit", {"request": {"file_path": str(source)}})
        prior = Path(earlier.structured_content["metadata"]["artifact"]["path"]).parent
        prior_bytes = {p.name: p.read_bytes() for p in prior.iterdir()}
        args = {"request": {"file_path": str(source), "engine": "vision"}}
        if canceled:
            task = asyncio.create_task(client.call_tool("image_ocr", args, raise_on_error=False))
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.wait_for(finished.wait(), 2)
        else:
            reply = await client.call_tool("image_ocr", args, raise_on_error=False)
            assert reply.structured_content["error"] == "controlled OCR backend failure"
        assert finished.is_set()
        assert set(prior.parent.iterdir()) == {prior}
        assert {p.name: p.read_bytes() for p in prior.iterdir()} == prior_bytes
    assert source.read_bytes() == original
