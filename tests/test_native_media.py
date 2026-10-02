"""Actual MCP discovery/schema and image/text transport without provider calls."""

import base64
import hashlib
import json
import shutil

from fastmcp import Client
from jsonschema import validate
import pytest

from video_research_mcp.tools.media import INLINE_IMAGE_BYTES, image_crop, media_server


async def test_native_and_text_clients_receive_identical_crop_identity(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("Optional independently installed FFmpeg unavailable")
    from tests.test_image_ops import png

    source = png(tmp_path / "source.png")
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    async with Client(media_server) as client:
        tools = await client.list_tools()
        tool = next(tool for tool in tools if tool.name == "image_crop")
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.open_world_hint is False
        assert tool.input_schema["properties"]["crop_box"]["maxItems"] == 4
        native = await client.call_tool(
            "image_crop",
            {
                "file_path": str(source),
                "output_path": str(tmp_path / "native.png"),
                "crop_box": [2, 0, 2, 2],
            },
        )
        text = await client.call_tool(
            "image_crop",
            {
                "file_path": str(source),
                "output_path": str(tmp_path / "text.png"),
                "crop_box": [2, 0, 2, 2],
                "include_image": False,
            },
        )
        validate(native.structured_content, tool.output_schema)
        validate(text.structured_content, tool.output_schema)
        assert [part.type for part in native.content] == ["text", "image"]
        assert [part.type for part in text.content] == ["text"]
        assert json.loads(native.content[0].text) == native.structured_content
        data = base64.b64decode(native.content[1].data)
        assert len(data) <= INLINE_IMAGE_BYTES
        assert hashlib.sha256(data).hexdigest() == native.structured_content["artifact_sha256"]
        assert (
            text.structured_content["artifact_sha256"]
            == native.structured_content["artifact_sha256"]
        )
        assert text.structured_content["source_sha256"] == original_hash
        assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash


async def test_errors_are_protocol_errors_without_artifact_paths(tmp_path):
    result = await image_crop(
        str(tmp_path / "missing.png"), str(tmp_path / "crop.png"), [0, 0, 1, 1]
    )
    assert result.is_error is True
    assert result.structured_content["category"] == "FILE_NOT_FOUND"
    assert "artifact" not in result.structured_content
    assert [part.type for part in result.content] == ["text"]
    assert not (tmp_path / "crop.png").exists()


async def test_inline_cap_falls_back_to_metadata(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("Optional independently installed FFmpeg unavailable")
    from tests.test_image_ops import png

    monkeypatch.setattr("video_research_mcp.tools.media.INLINE_IMAGE_BYTES", 10)
    result = await image_crop(
        str(png(tmp_path / "source.png")), str(tmp_path / "crop.png"), [0, 0, 1, 1]
    )
    assert not result.is_error
    assert result.structured_content["native_image_status"] == "inline_byte_limit"
    assert [part.type for part in result.content] == ["text"]


@pytest.mark.parametrize("coordinate", [True, 1.5, float("nan"), float("inf")])
async def test_mcp_rejects_noninteger_coordinates_before_any_write(coordinate, tmp_path):
    async with Client(media_server) as client:
        result = await client.call_tool(
            "image_crop",
            {
                "file_path": str(tmp_path / "source.png"),
                "output_path": str(tmp_path / "crop.png"),
                "crop_box": [0, 0, coordinate, 1],
            },
            raise_on_error=False,
        )
    assert result.is_error
    assert not (tmp_path / "crop.png").exists()
