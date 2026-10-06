"""Published effect hints and fenced inline-video preparation boundaries."""

import hashlib
from pathlib import Path

import pytest

from video_research_mcp.models.execution import ExecutionLimits
from video_research_mcp.tools import video, video_plan


def _limits():
    """Reserve one counted and generated static window without submitting it."""
    return ExecutionLimits(max_calls=2, max_tokens=2000, max_output_tokens=100,
                           max_frames=2, max_windows=2, start_ms=0, end_ms=1000, fps=1.0)


def _plan(path, body):
    """Bind finite prepared inline bytes to their original source commitment."""
    return {"launch_blockers": [], "remote_payloads": [{"source": {
        "kind": "local_file", "path": str(path), "sha256": hashlib.sha256(body).hexdigest(),
    }}]}


async def test_batch_annotations_describe_durable_external_effects():
    """GIVEN batch registration THEN its published hints permit additive external effects."""
    tool = await video.video_server.get_tool("video_batch_analyze")
    hints = tool.annotations.model_dump(by_alias=True)
    assert hints["readOnlyHint"] is False
    assert hints["destructiveHint"] is False
    assert hints["idempotentHint"] is False
    assert hints["openWorldHint"] is True


def test_inline_substitution_rejects_same_bytes_symlink(tmp_path, monkeypatch, clean_config):
    """GIVEN an allowed file replaced after validation THEN a symlink cannot be reopened."""
    source, alternate = tmp_path / "source.mp4", tmp_path / "alternate.mp4"
    body = b"same bounded inline bytes"
    source.write_bytes(body)
    alternate.write_bytes(body)
    validate = video_plan._validate_video_path

    def swap(path):
        result = validate(path)
        source.unlink()
        source.symlink_to(alternate)
        return result

    monkeypatch.setattr(video_plan, "_validate_video_path", swap)
    with pytest.raises(PermissionError, match="regular"):
        video_plan.bounded_contents(_plan(source, body), "Inspect", _limits())


def test_inline_substitution_rejects_fifo_before_blocking_open(
    tmp_path, monkeypatch, clean_config,
):
    """GIVEN a substituted FIFO THEN refuse it without attempting a blocking pathname open."""
    import os

    source = tmp_path / "source.mp4"
    body = b"bounded original bytes"
    source.write_bytes(body)
    validate, ordinary_open = video_plan._validate_video_path, Path.open

    def swap(path):
        result = validate(path)
        source.unlink()
        os.mkfifo(source)
        return result

    def refuse_blocking_open(path, *args, **kwargs):
        if path == source:
            raise AssertionError("Blocking FIFO pathname open reached")
        return ordinary_open(path, *args, **kwargs)

    monkeypatch.setattr(video_plan, "_validate_video_path", swap)
    monkeypatch.setattr(Path, "open", refuse_blocking_open)
    with pytest.raises(PermissionError, match="regular"):
        video_plan.bounded_contents(_plan(source, body), "Inspect", _limits())


def test_inline_regular_bytes_and_window_are_preserved(tmp_path, clean_config):
    """GIVEN unchanged regular bytes THEN inline data and requested source clocks survive."""
    source = tmp_path / "source.mp4"
    body = b"bounded original bytes"
    source.write_bytes(body)
    result = video_plan.bounded_contents(_plan(source, body), "Inspect", _limits())
    assert result.parts[0].inline_data.data == body
    assert result.parts[0].video_metadata.start_offset == "0.000s"
    assert result.parts[0].video_metadata.end_offset == "1.000s"


def test_inline_changed_hash_still_refuses(tmp_path, clean_config):
    """GIVEN different current bytes THEN the original hash commitment still fails closed."""
    source = tmp_path / "source.mp4"
    source.write_bytes(b"changed bytes")
    with pytest.raises(ValueError, match="changed"):
        video_plan.bounded_contents(_plan(source, b"original bytes"), "Inspect", _limits())


def test_inline_byte_ceiling_still_refuses(tmp_path, monkeypatch, clean_config):
    """GIVEN bytes at the inline ceiling THEN preparation still refuses the payload."""
    source = tmp_path / "source.mp4"
    body = b"x" * 64
    source.write_bytes(body)
    monkeypatch.setattr(video_plan, "LARGE_FILE_THRESHOLD", 64)
    with pytest.raises(ValueError, match="inline budget"):
        video_plan.bounded_contents(_plan(source, body), "Inspect", _limits())
