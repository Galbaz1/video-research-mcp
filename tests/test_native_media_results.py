"""Native transport bounds and provenance validation without inference or media decoding."""

import base64
import hashlib
import json

import pytest

from tests.test_image_ops import png
from video_research_mcp.models.native_media import FrameTranscript
from video_research_mcp.native_media_results import native_operation, native_result


def metadata(path):
    """Build one deterministic still result with actual fixture bytes."""
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    return {
        "source": {
            "path": str(path), "sha256": digest, "bytes": len(data), "source_revision": digest,
            "duration_seconds": None, "container_start_seconds": None,
            "stored_width": 4, "stored_height": 2, "display_width": 4, "display_height": 2,
            "rotation_degrees": None, "time_base": None, "stream_index": None,
            "streams": [], "chapters": [], "metadata_method": "fixture_header",
        },
        "frames": [{
            "path": str(path), "sha256": digest, "bytes": len(data), "width": 4, "height": 2,
            "requested_seconds": None, "actual_seconds": None, "original_pts": None,
            "time_base": None, "selection_method": "first_still", "approximate": False,
            "delta_seconds": None, "crop_box": None,
        }],
        "coverage": {
            "sampled_points": [], "decoded_count": 1, "requested_window": None,
            "complete": True, "stop_reason": None, "watched_intervals": [],
        },
        "status": "complete", "limits": {},
    }


async def test_native_and_text_preserve_exact_identity_and_no_watched_interval(tmp_path):
    value = metadata(png(tmp_path / "frame.png"))
    native = await native_result(value, True)
    text = await native_result(value, False)
    assert [part.type for part in native.content] == ["text", "image"]
    assert [part.type for part in text.content] == ["text"]
    assert native.structured_content["source"] == text.structured_content["source"]
    assert native.structured_content["coverage"] == text.structured_content["coverage"]
    assert native.structured_content["coverage"]["watched_intervals"] == []
    data = base64.b64decode(native.content[1].data)
    assert hashlib.sha256(data).hexdigest() == value["frames"][0]["sha256"]
    assert json.loads(native.content[0].text) == native.structured_content
    assert native.structured_content["native_image_status"] == "included"
    assert text.structured_content["native_image_status"] == "text_only"


async def test_changed_artifact_fails_before_returning_native_content(tmp_path):
    path = png(tmp_path / "frame.png")
    value = metadata(path)
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed before native transport"):
        await native_result(value, True)


@pytest.mark.parametrize("mode", ["text", "inline_fallback"])
@pytest.mark.parametrize("mutation", ["missing", "changed"])
async def test_text_and_inline_fallback_verify_every_artifact(mode, mutation, tmp_path, monkeypatch):
    path = png(tmp_path / "frame.png")
    value = metadata(path)
    if mode == "inline_fallback":
        monkeypatch.setattr("video_research_mcp.native_media_results.INLINE_IMAGE_BYTES", 1)
    if mutation == "missing":
        path.unlink()
    else:
        path.write_bytes(b"changed artifact")
    with pytest.raises((FileNotFoundError, ValueError)):
        await native_result(value, mode != "text")


async def test_per_image_and_aggregate_fallback_preserve_all_frame_metadata(tmp_path, monkeypatch):
    value = metadata(png(tmp_path / "frame.png"))
    size = value["frames"][0]["bytes"]
    monkeypatch.setattr("video_research_mcp.native_media_results.INLINE_IMAGE_BYTES", size - 1)
    limited = await native_result(value, True)
    assert [part.type for part in limited.content] == ["text"]
    assert limited.structured_content["frames"][0]["native_image_status"] == "inline_byte_limit"
    monkeypatch.setattr("video_research_mcp.native_media_results.INLINE_IMAGE_BYTES", size)
    monkeypatch.setattr("video_research_mcp.native_media_results.INLINE_TOTAL_BYTES", size)
    value["frames"] *= 2
    limited = await native_result(value, True)
    assert [part.type for part in limited.content] == ["text", "image"]
    assert len(limited.structured_content["frames"]) == 2
    assert limited.structured_content["frames"][1]["native_image_status"] == "inline_total_limit"
    assert limited.structured_content["native_image_status"] == "partial"


async def test_substituted_fifo_and_symlink_never_open_as_native_artifacts(tmp_path):
    import os

    path = png(tmp_path / "frame.png")
    value = metadata(path)
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(PermissionError, match="regular"):
        await native_result(value, True)
    path.unlink()
    target = png(tmp_path / "target.png")
    path.symlink_to(target)
    with pytest.raises(PermissionError, match="regular"):
        await native_result(value, True)


@pytest.mark.parametrize("start,end", [(1, 0), (float("nan"), 1), (0, float("inf"))])
def test_transcript_rejects_unusable_times(start, end):
    with pytest.raises(ValueError):
        FrameTranscript.model_validate({
            "source_sha256": "a" * 64,
            "segments": [{"start_seconds": start, "end_seconds": end, "text": "state on"}],
        })


def test_transcript_has_real_aggregate_text_bound():
    segments = [{"start_seconds": 0, "end_seconds": 1, "text": "x" * 4096}] * 17
    with pytest.raises(ValueError, match="64 KiB"):
        FrameTranscript.model_validate({"source_sha256": "a" * 64, "segments": segments})


async def test_transport_cancellation_joins_actual_image_worker(tmp_path, monkeypatch):
    import asyncio
    import threading

    started, finished = threading.Event(), threading.Event()

    def controlled_transport(result, include_image, canceled):
        started.set()
        assert canceled.wait(2)
        finished.set()
        return []

    monkeypatch.setattr("video_research_mcp.native_media_results._native_blocks", controlled_transport)
    task = asyncio.create_task(native_result(metadata(png(tmp_path / "frame.png")), True))
    assert await asyncio.to_thread(started.wait, 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()


@pytest.mark.parametrize("canceled", [False, True])
async def test_failed_ocr_transport_removes_both_owned_exports_only(
    tmp_path, monkeypatch, clean_config, canceled
):
    """A failed final delivery removes prepared and raw slots while preserving input."""
    import asyncio

    cache = tmp_path / "cache"
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(cache))
    original = png(tmp_path / "source.png")
    before = original.read_bytes()
    prepared = cache / "media" / "views" / ("a" * 32)
    raw = cache / "media" / "views" / ("b" * 32)
    for directory in (prepared, raw):
        directory.mkdir(parents=True)
    artifact = png(prepared / "prepared.png")
    payload = raw / "observations.json"
    payload.write_text('{"observed":true}')
    error = asyncio.CancelledError if canceled else RuntimeError
    with pytest.raises(error):
        async with native_operation() as produced:
            produced.append({"artifacts": [{"path": str(artifact)}, {"path": str(payload)}]})
            raise error("delivery interrupted")
    assert not prepared.exists() and not raw.exists()
    assert original.read_bytes() == before
