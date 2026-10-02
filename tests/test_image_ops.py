"""PNG preflight rejects unsafe inputs before the optional decoder starts."""

import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
from unittest.mock import Mock
import zlib

import pytest

from video_research_mcp.image_ops import crop_png, inspect_png


def png(path: Path, width: int = 4, height: int = 4, *, header_only: bool = False):
    """Make an original RGB PNG with a red/blue split, or a bounded bomb header."""

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    body = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
    if not header_only:
        row = b"\x00" + b"\xff\x00\x00" * (width // 2) + b"\x00\x00\xff" * (width - width // 2)
        body += chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b"")
    path.write_bytes(body)
    return path


@pytest.mark.parametrize(
    "box",
    [
        (-1, 0, 1, 1),
        (0, 0, 0, 1),
        (0, 0, 5, 1),
        (0, 0, float("nan"), 1),
        (0, 0, float("inf"), 1),
        (0, 0, True, 1),
    ],
)
def test_crop_bounds_precede_subprocess(box, tmp_path, monkeypatch):
    source = png(tmp_path / "source.png")
    spawn = Mock(side_effect=AssertionError("decoder must not start"))
    monkeypatch.setattr("video_research_mcp.image_ops.subprocess.run", spawn)
    with pytest.raises(ValueError, match="Crop"):
        crop_png(str(source), str(tmp_path / "output.png"), box)
    spawn.assert_not_called()
    assert not (tmp_path / "output.png").exists()


def test_image_bomb_rejected_from_header_before_decode(tmp_path, monkeypatch):
    source = png(tmp_path / "bomb.png", 100_000, 100_000, header_only=True)
    spawn = Mock(side_effect=AssertionError("decoder must not start"))
    monkeypatch.setattr("video_research_mcp.image_ops.subprocess.run", spawn)
    with pytest.raises(ValueError, match="input pixel ceiling"):
        crop_png(str(source), str(tmp_path / "output.png"), (0, 0, 1, 1))
    spawn.assert_not_called()


def test_output_pixel_ceiling_precedes_decode(tmp_path, monkeypatch):
    source = png(tmp_path / "large.png", 2500, 2000, header_only=True)
    spawn = Mock(side_effect=AssertionError("decoder must not start"))
    monkeypatch.setattr("video_research_mcp.image_ops.subprocess.run", spawn)
    with pytest.raises(ValueError, match="output pixel ceiling"):
        crop_png(str(source), str(tmp_path / "output.png"), (0, 0, 2500, 2000))
    spawn.assert_not_called()


def test_byte_ceiling_precedes_header_read(tmp_path, monkeypatch, clean_config):
    source = png(tmp_path / "source.png")
    monkeypatch.setenv("MEDIA_MAX_INPUT_BYTES", "10")
    with pytest.raises(ValueError, match="MEDIA_MAX_INPUT_BYTES"):
        inspect_png(str(source))


def test_header_corruption_and_source_fence(tmp_path, monkeypatch, clean_config):
    source = png(tmp_path / "source.png")
    data = bytearray(source.read_bytes())
    data[20] ^= 1
    source.write_bytes(data)
    with pytest.raises(ValueError, match="checksum"):
        inspect_png(str(source))
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(allowed))
    from video_research_mcp import config

    config._config = None
    with pytest.raises(PermissionError, match="LOCAL_FILE_ACCESS_ROOT"):
        inspect_png(str(source))


def test_missing_decoder_is_explicit_without_output(tmp_path, monkeypatch):
    source = png(tmp_path / "source.png")
    monkeypatch.setattr("video_research_mcp.image_ops.shutil.which", lambda _: None)
    with pytest.raises(RuntimeError, match="independently installed FFmpeg"):
        crop_png(str(source), str(tmp_path / "output.png"), (0, 0, 2, 2))
    assert not (tmp_path / "output.png").exists()


def test_real_crop_decodes_expected_pixels_and_preserves_original(tmp_path):
    executable = shutil.which("ffmpeg")
    if not executable:
        pytest.skip("Optional independently installed FFmpeg is unavailable")
    source = png(tmp_path / "source.png")
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    target = tmp_path / "crop.png"
    result = crop_png(str(source), str(target), (2, 0, 2, 2))
    assert result["source_sha256"] == original_hash
    assert result["crop_box"] == [2, 0, 2, 2]
    assert result["artifact_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    decoded = subprocess.run(
        [
            executable,
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(target),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=5,
    ).stdout
    assert decoded == b"\x00\x00\xff" * 4


def test_changed_source_after_header_cannot_rebind_metadata(tmp_path, monkeypatch):
    from video_research_mcp import image_ops

    source = png(tmp_path / "source.png")
    original_digest = image_ops._source_digest
    first = True

    def mutate(path):
        nonlocal first
        if first:
            first = False
            png(source, 6, 6)
        return original_digest(path)

    monkeypatch.setattr(image_ops, "_source_digest", mutate)
    monkeypatch.setattr(image_ops.shutil, "which", lambda _: "ffmpeg")
    spawn = Mock(side_effect=AssertionError("changed source must not reach decoder"))
    monkeypatch.setattr(image_ops.subprocess, "run", spawn)
    with pytest.raises(ValueError, match="changed after header"):
        crop_png(str(source), str(tmp_path / "out.png"), (0, 0, 2, 2))
    spawn.assert_not_called()
    assert not (tmp_path / "out.png").exists()
