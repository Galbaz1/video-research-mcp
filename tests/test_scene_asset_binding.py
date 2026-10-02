"""Controlled substitutions cannot separate scene content from its byte commitment."""
import hashlib
import io
import time
from contextlib import contextmanager
from pathlib import Path
import threading
from unittest.mock import AsyncMock

from PIL import Image
import pytest

from tests.test_audio_assets import audio_source
from tests.test_media_storyboard import fixed_media, source_request
from video_research_mcp import audio_assets, media_frames, media_storyboard
from video_research_mcp.config import get_config
from video_research_mcp.models.scene_assets import AudioExportRequest, StoryboardRequest

__all__ = ["audio_source", "fixed_media"]


@pytest.fixture(autouse=True)
def owned_outputs(clean_config, monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("LOCAL_FILE_ACCESS_ROOT", raising=False)


def test_storyboard_rejects_different_pixels_between_identity_and_decode(tmp_path, monkeypatch):
    buffers = []
    for color in ("red", "blue"):
        with Image.new("RGB", (16, 16), color) as image:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            buffers.append(buffer.getvalue())
    buffers = [data.ljust(max(map(len, buffers)), b"\0") for data in buffers]
    path = tmp_path / "frame.png"
    path.write_bytes(buffers[0])
    frame = {"path": str(path), "sha256": hashlib.sha256(buffers[0]).hexdigest(),
             "bytes": len(buffers[0]), "width": 16, "height": 16,
             "actual_seconds": .5, "original_pts": 5, "time_base": "1/10"}
    @contextmanager
    def replaced_reader(_):
        with io.BytesIO(buffers[1]) as reader:
            yield reader
    monkeypatch.setattr(media_storyboard, "_open_regular", replaced_reader)
    with pytest.raises(ValueError, match="frame changed before composition"):
        media_storyboard._compose([frame], 1, tmp_path, threading.Event(), time.monotonic() + 10)


async def test_wav_replacement_after_pcm_readback_cannot_publish_inconsistent_hashes(audio_source, monkeypatch):
    path, source_sha = audio_source
    original_readback = audio_assets.wav_readback
    def replace_after_readback(output_path, cancelled, deadline):
        result = original_readback(output_path, cancelled, deadline)
        data = bytearray(Path(output_path).read_bytes())
        data[-2] ^= 1
        Path(output_path).write_bytes(data)
        return result
    monkeypatch.setattr(audio_assets, "wav_readback", replace_after_readback)
    with pytest.raises(ValueError, match="(?i)(changed|commitment|identity|digest)"):
        await audio_assets.export_audio(AudioExportRequest(file_path=str(path), expected_source_sha256=source_sha))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == source_sha
    views = Path(get_config().cache_dir) / "media" / "views"
    assert not views.exists() or not list(views.iterdir())


async def test_nested_storyboard_sampler_is_bound_and_returned_source_is_verified(fixed_media, monkeypatch):
    fixture = fixed_media["cfr"]
    views = Path(get_config().cache_dir) / "media" / "views"
    prior = views / "previous"
    prior.mkdir(parents=True)
    (prior / "sentinel").write_bytes(b"preserve")
    real_sampler = media_storyboard.sample_frames
    observed = {}
    async def different_source(path, **kwargs):
        observed["expected_source_sha256"] = kwargs.get("expected_source_sha256")
        result = await real_sampler(path, **kwargs)
        result["source"]["sha256"] = "b" * 64
        return result
    monkeypatch.setattr(media_storyboard, "sample_frames", different_source)
    with pytest.raises(ValueError, match="Storyboard sampled source commitment"):
        await media_storyboard.create_storyboard(StoryboardRequest(**source_request(
            fixture, start_seconds=.2, end_seconds=1, columns=2, rows=1)))
    assert observed["expected_source_sha256"] == fixture["sha256"]
    assert list(views.iterdir()) == [prior]
    assert (prior / "sentinel").read_bytes() == b"preserve"


async def test_sampler_stale_source_commitment_fails_before_probe(fixed_media, monkeypatch):
    fixture = fixed_media["cfr"]
    probe = AsyncMock()
    monkeypatch.setattr(media_frames, "probe_snapshot", probe)
    with pytest.raises(ValueError, match="Source SHA256"):
        await media_frames.sample_frames(fixture["path"], expected_source_sha256="b" * 64)
    probe.assert_not_awaited()
    views = Path(get_config().cache_dir) / "media" / "views"
    assert not views.exists() or not list(views.iterdir())
