"""Artifact identity and native transport controls for image operations."""

import base64
import hashlib
import os

import pytest

from video_research_mcp.image_tool_results import image_blocks


def artifact(path, mime="image/png"):
    """Bind exact fixture bytes to the operation's declared identity."""
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "mime": mime}


async def test_native_payload_is_exact_and_text_mode_retains_identity(tmp_path):
    path = tmp_path / "source.png"
    path.write_bytes(b"controlled exact bytes")
    metadata = {"artifacts": [artifact(path)]}
    blocks, delivery = await image_blocks(metadata, True)
    assert base64.b64decode(blocks[0].data) == path.read_bytes()
    assert delivery == [{"path": str(path), "mime": "image/png", "status": "included"}]
    blocks, delivery = await image_blocks(metadata, False)
    assert blocks == [] and delivery[0]["status"] == "text_only"


@pytest.mark.parametrize("include", [True, False])
@pytest.mark.parametrize("mutation", ["change", "missing", "fifo", "symlink"])
async def test_all_transports_reject_changed_or_nonregular_artifacts(tmp_path, include, mutation):
    """GIVEN retained output WHEN changed THEN native/text transport cannot endorse it."""
    path = tmp_path / "result.png"
    path.write_bytes(b"original artifact")
    metadata = {"artifacts": [artifact(path)]}
    path.unlink()
    if mutation == "change":
        path.write_bytes(b"changed")
    elif mutation == "fifo":
        os.mkfifo(path)
    elif mutation == "symlink":
        target = tmp_path / "unrelated.png"
        target.write_bytes(b"unrelated")
        path.symlink_to(target)
    with pytest.raises((ValueError, FileNotFoundError, PermissionError)):
        await image_blocks(metadata, include)


async def test_inline_fallback_and_nonimage_artifacts_still_verify(tmp_path, monkeypatch):
    image = tmp_path / "frame.png"
    raw = tmp_path / "raw.json"
    image.write_bytes(b"image")
    raw.write_bytes(b"{\"text\":\"observation\"}")
    value = {"artifacts": [artifact(image), artifact(raw, "application/json")]}
    monkeypatch.setattr("video_research_mcp.image_tool_results.INLINE_IMAGE_BYTES", 1)
    blocks, delivery = await image_blocks(value, True)
    assert blocks == [] and delivery[0]["status"] == "inline_byte_limit"
    raw.write_bytes(b"changed raw observation")
    with pytest.raises(ValueError, match="changed"):
        await image_blocks(value, False)


@pytest.mark.parametrize("mime", ["image/bmp", "image/gif"])
async def test_converted_formats_have_explicit_native_transport_limit(tmp_path, mime):
    path = tmp_path / "conversion"
    path.write_bytes(b"exact converted fixture bytes")
    blocks, delivery = await image_blocks({"artifacts": [artifact(path, mime)]}, True)
    assert blocks == [] and delivery[0]["status"] == "unsupported_native_mime"
