"""Native image input/output guards, exact restart identities and joined cleanup."""

import asyncio
import os
import threading
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from video_research_mcp.image_edit import edit_image
from video_research_mcp.image_manifest import read_manifest
from video_research_mcp.models.image_edit import ImageEditRequest


@pytest.fixture(autouse=True)
def isolate_image_views(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.png"
    Image.new("RGBA", (80, 60), (10, 20, 30, 255)).save(path)
    return path


@pytest.mark.parametrize("changes", [
    {"crop": {"coordinates": [True, 0, 2, 2]}},
    {"crop": {"coordinates": [0.0, 0, 2, 2]}},
    {"crop": {"space": "normalized1000", "coordinates": [0, 0, 1001, 1000]}},
    {"annotations": [{"kind": "box", "coordinates": [0, 0, float("nan"), 2]}]},
    {"annotations": [{"kind": "text", "coordinates": ["1", 2], "text": "x"}]},
    {"annotations": [{"kind": "box", "coordinates": [0, 0, 2, 2]}] * 33},
    {"quality": 101}, {"time_seconds": float("inf")}, {"file_path": "x" * 4097}])
def test_invalid_boundaries_reject_before_filesystem(changes):
    with pytest.raises(ValidationError):
        ImageEditRequest.model_validate({"file_path": "/missing.png", **changes})


@pytest.mark.parametrize("damage", ["symlink", "fifo", "outside_fence", "wrong_sha"])
async def test_source_boundary_preserves_original_without_outputs(source, tmp_path, monkeypatch, damage):
    request = ImageEditRequest(file_path=str(source))
    if damage in {"symlink", "fifo"}:
        hostile = tmp_path / "hostile.png"
        hostile.symlink_to(source) if damage == "symlink" else os.mkfifo(hostile)
        request = request.model_copy(update={"file_path": str(hostile)})
    elif damage == "outside_fence":
        (tmp_path / "allowed").mkdir()
        monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path / "allowed"))
    else:
        request = request.model_copy(update={"expected_source_sha256": "0" * 64})
    before = source.read_bytes()
    with pytest.raises((PermissionError, ValueError)):
        await edit_image(request)
    assert source.read_bytes() == before
    assert not list((tmp_path / "cache" / "media" / "views").glob("*"))


@pytest.mark.parametrize("guard", ["bytes", "pixels"])
async def test_source_byte_and_decoded_pixel_limits_before_load(tmp_path, guard):
    source = tmp_path / "oversized.png"
    if guard == "bytes":
        source.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    else:
        Image.new("RGB", (4000, 2001)).save(source)
    with pytest.raises(ValueError, match="16 MiB|8 megapixel"):
        await edit_image(ImageEditRequest(file_path=str(source)))
    assert not list((tmp_path / "cache" / "media" / "views").glob("*"))


async def test_closeup_aggregate_preflight_rejects_many_large_copies(tmp_path):
    source = tmp_path / "closeups.png"
    Image.new("RGB", (1000, 1000), "white").save(source)
    annotations = [{"kind": "box", "coordinates": [100, 100, 732, 732], "closeup_padding": 0.4}] * 32
    with pytest.raises(ValueError, match="16 megapixel"):
        await edit_image(ImageEditRequest(file_path=str(source), annotations=annotations))
    assert not list((tmp_path / "cache" / "media" / "views").glob("*"))


async def test_encoded_byte_budget_fails_without_partial_outputs(source, monkeypatch, tmp_path):
    monkeypatch.setattr("video_research_mcp.image_edit.MAX_ARTIFACT_BYTES", 20)
    with pytest.raises(ValueError, match="aggregate byte"):
        await edit_image(ImageEditRequest(file_path=str(source)))
    assert not list((tmp_path / "cache" / "media" / "views").glob("*"))


@pytest.mark.parametrize("damage", ["manifest", "artifact", "missing", "symlink", "source"])
async def test_manifest_readback_refuses_changed_identity(source, damage):
    result = await edit_image(ImageEditRequest(file_path=str(source)))
    artifact = Path(result["artifact"]["path"])
    if damage == "manifest":
        Path(result["manifest"]["path"]).write_text("{}")
    elif damage == "artifact":
        artifact.write_bytes(b"modified artifact")
    elif damage == "missing":
        artifact.unlink()
    elif damage == "symlink":
        artifact.unlink()
        artifact.symlink_to(source)
    else:
        source.write_bytes(b"modified original")
    with pytest.raises((ValueError, PermissionError, FileNotFoundError)):
        await read_manifest(result["manifest"]["path"], result["manifest"]["sha256"])


async def test_source_mutation_during_encode_fails_and_preserves_new_source(source, monkeypatch, tmp_path):
    from video_research_mcp import image_edit
    original_save = image_edit.save_artifact
    def mutate(*args):
        artifact = original_save(*args)
        source.write_bytes(b"new owner revision")
        return artifact
    monkeypatch.setattr(image_edit, "save_artifact", mutate)
    with pytest.raises(ValueError, match="identity changed"):
        await edit_image(ImageEditRequest(file_path=str(source)))
    assert source.read_bytes() == b"new owner revision"
    assert not list((tmp_path / "cache" / "media" / "views").glob("*"))


async def test_cancellation_joins_worker_before_owned_staging_removal(source, monkeypatch, tmp_path):
    from video_research_mcp import image_edit
    entered, release = threading.Event(), threading.Event()
    original_load = image_edit.load_oriented
    def blocked(*args):
        entered.set()
        release.wait(2)
        return original_load(*args)
    monkeypatch.setattr(image_edit, "load_oriented", blocked)
    before = source.read_bytes()
    task = asyncio.create_task(edit_image(ImageEditRequest(file_path=str(source))))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done()
        assert list((tmp_path / "cache" / "media" / "views").glob("*/source.png"))
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert source.read_bytes() == before
    assert not list((tmp_path / "cache" / "media" / "views").glob("*"))
