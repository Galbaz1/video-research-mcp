"""Probe, optional companion grant checks and mocked recording boundaries."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from video_research_mcp import live_companion as companion
from video_research_mcp.models.live import CaptureRequest, ProbeRequest, RecordingAuthority
from video_research_mcp.tools.live import live_capability_probe, live_capture_prepare, live_server


@pytest.fixture
def companion_fixture(tmp_path, monkeypatch, clean_config):
    """Self-contained dummy byte commitments; actual upstream pins are separately rehashed."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    root = tmp_path / "companion"
    expected = {}
    for relative in companion.PRIMARY:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = ("independent dummy fixture bytes: " + relative).encode()
        target.write_bytes(raw)
        expected[relative] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(companion, "PRIMARY", expected)
    return root


def capture_request(root, output):
    """One explicit dummy window-operation scope, never a real recording grant."""
    return CaptureRequest(companion_root=str(root), output_dir=str(output), authority=RecordingAuthority(
        operation_id="unit-dummy-operation", target="window", window_title="unit dummy window",
        duration_seconds=1.0, retention="unit fixture only; no actual device authorization"))


async def test_probe_inspects_files_without_executing_or_recording(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    device = tmp_path / "dummy-device-node"
    device.write_bytes(b"unit fixture, not a device")
    monkeypatch.setattr(companion.shutil, "which", lambda _: None)
    forbidden = Mock(side_effect=AssertionError("probe must not record"))
    monkeypatch.setattr(companion, "run_capture", forbidden)
    result = await live_capability_probe(ProbeRequest(device_paths=[str(device), str(tmp_path / "missing-node")]))
    assert result["recording_started"] is False
    assert result["data"]["ffmpeg_executable_present"] is False
    assert [d["present"] for d in result["data"]["devices"]] == [True, False]
    assert all(d["recording_permission"] == "UNKNOWN" for d in result["data"]["devices"])
    assert result["data"]["capture_support"] == "unsupported"
    forbidden.assert_not_called()


async def test_unsupported_platform_returns_before_output_or_foreign_import(companion_fixture, tmp_path, monkeypatch):
    monkeypatch.setattr(companion, "sys", SimpleNamespace(platform="darwin", path=[]))
    monkeypatch.setattr(companion.shutil, "which", lambda _: "/dummy/ffmpeg")
    import importlib

    forbidden = Mock(side_effect=AssertionError("must not import capture runtime"))
    monkeypatch.setattr(importlib, "import_module", forbidden)
    request = capture_request(companion_fixture, tmp_path / "no-recording-output")
    result = await live_capture_prepare(request)
    assert result["status"] == "unsupported"
    assert result["recording_started"] is False
    assert result["data"]["companion_source"] == "pinned_source_verified"
    assert not Path(request.output_dir).exists()
    forbidden.assert_not_called()


def test_exact_grant_and_sources_are_checked_before_foreign_import(companion_fixture, tmp_path, monkeypatch):
    (companion_fixture / "LICENSE").write_text("different grant")
    monkeypatch.setattr(companion, "sys", SimpleNamespace(platform="win32", path=[]))
    monkeypatch.setattr(companion.shutil, "which", lambda _: "/dummy/ffmpeg")
    request = capture_request(companion_fixture, tmp_path / "untouched")
    result = companion.run_capture(request)
    assert result["status"] == "unsupported"
    assert not Path(request.output_dir).exists()


def test_missing_dependency_refuses_before_recording_output(companion_fixture, tmp_path, monkeypatch):
    import importlib

    monkeypatch.setattr(companion, "sys", SimpleNamespace(platform="win32", path=[]))
    monkeypatch.setattr(companion.shutil, "which", lambda _: "/dummy/ffmpeg")
    monkeypatch.setattr(importlib, "import_module", Mock(side_effect=ImportError("unit missing companion")))
    request = capture_request(companion_fixture, tmp_path / "no-recording-output")
    result = companion.run_capture(request)
    assert result["status"] == "unsupported"
    assert result["data"]["reason"] == "companion_runtime_dependency_missing"
    assert not Path(request.output_dir).exists()


def test_optional_source_defined_adapter_with_dummy_external_capture(companion_fixture, tmp_path, monkeypatch):
    """GIVEN a mocked foreign capture API WHEN explicitly invoked THEN exact scope and artifact are retained."""
    import importlib

    calls = []

    def dummy_capture(output, *, duration_seconds, window_title):
        calls.append((duration_seconds, window_title))
        path = output / "capture.mp4"
        path.write_bytes(b"subprocess/service dummy artifact; not real captured media")
        return SimpleNamespace(video_path=path)

    module = SimpleNamespace(__file__=str(companion_fixture / "src/watch_skill/loop/capture.py"),
                             capture_screen=dummy_capture)
    monkeypatch.setattr(companion, "sys", SimpleNamespace(platform="win32", path=[]))
    monkeypatch.setattr(companion.shutil, "which", lambda _: "/dummy/ffmpeg")
    monkeypatch.setattr(importlib, "import_module", lambda _: module)
    request = capture_request(companion_fixture, tmp_path / "dummy-output")
    result = companion.run_capture(request)
    assert calls == [(1.0, "unit dummy window")]
    assert result["native_acceptance"] == "NOT_QUALIFIED"
    assert result["authority"] == request.authority.model_dump()
    assert Path(result["artifact"]["path"]).read_bytes().startswith(b"subprocess/service dummy")
    with pytest.raises(FileExistsError):
        companion.run_capture(request)
    assert len(calls) == 1


def test_no_recording_scope_defaults_or_unmatched_target_are_accepted(tmp_path):
    with pytest.raises(ValidationError):
        CaptureRequest(companion_root=str(tmp_path), output_dir=str(tmp_path / "output"))
    with pytest.raises(ValidationError, match="window_title"):
        RecordingAuthority(operation_id="explicit", target="window", duration_seconds=1.0, retention="unit")
    with pytest.raises(ValidationError):
        RecordingAuthority(operation_id="explicit", target="screen", duration_seconds=31.0, retention="unit")


async def test_live_tools_are_discoverable_on_owned_subserver_without_root_mount():
    tools = await live_server.list_tools()
    assert {t.name for t in tools} == {"live_replay", "live_read", "live_monitor", "live_stop",
                                    "live_finalize", "live_capability_probe", "live_capture_prepare"}
    assert all(t.output_schema is not None for t in tools)


def test_core_startup_does_not_import_foreign_companion(tmp_path):
    """GIVEN an import trap WHEN the owned subserver loads THEN optional runtime stays absent."""
    package = tmp_path / "watch_skill"
    package.mkdir()
    (package / "__init__.py").write_text("raise AssertionError('foreign companion imported at core startup')")
    code = (
        "from pathlib import Path; import video_research_mcp.dotenv as d; "
        "d.DEFAULT_ENV_PATH=Path('/nonexistent-r173-unit-env'); "
        "import video_research_mcp.tools.live; import sys; "
        "assert 'watch_skill' not in sys.modules; print('independent core import')"
    )
    result = subprocess.run([sys.executable, "-c", code],
                            env={**os.environ, "PYTHONPATH": str(tmp_path) + os.pathsep + "src",
                                 "PYTHONDONTWRITEBYTECODE": "1"},
                            capture_output=True, text=True, timeout=20, check=True)
    assert result.stdout.strip() == "independent core import"
