"""Optional operator-run watch-skill capture; no foreign import during core startup."""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from .live_replay import MAX_ARCHIVE_BYTES, read_bytes
from .media_snapshot import checked_path
from .models.live import CaptureRequest, LiveResult, ProbeRequest

REVISION = "f1317c8fe64744a606c31867b05fbbe3144268c6"
PRIMARY = {
    "src/watch_skill/live/session.py": "42a3114b58d611d7fc5244030b7f0cf59d79610a5bd590108de21bb835994304",
    "src/watch_skill/loop/capture.py": "1348ec2149176962a45cccfd24b891ba10d1c96a96113d5ee686e9a7d9ca3dde",
    "src/watch_skill/observer/loop.py": "c9bca2b90e9a2bd47370c28f6a63afc1e8a98c9378e6e1bd1328c8a533f019dd",
    "src/watch_skill/triggers/engine.py": "83ba974c622d41ce524fc8afc02fa2e560004a8da70f400cfde68d53fa86cc71",
    "LICENSE": "eebd1fe1e58c6555775697c05bdec184584aeeb0ae11b18fcb5403c2ebc4d1ad",
}


def _sources(root_value: str) -> Path:
    """Verify exact source/grant bytes before any optional foreign import."""
    root = checked_path(root_value)
    for relative, digest in PRIMARY.items():
        raw = read_bytes(root / relative, MAX_ARCHIVE_BYTES)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Optional watch-skill source/license differs from pinned revision")
    return root


def probe(request: ProbeRequest) -> dict:
    """Observe executable/filesystem state without launching a binary, device or recorder."""
    devices = []
    for value in request.device_paths:
        path = checked_path(value)
        devices.append({"path": str(path), "present": path.exists(),
                        "filesystem_readable": os.access(path, os.R_OK),
                        "recording_permission": "UNKNOWN", "basis": "filesystem_metadata_only"})
    source_state, reason = "not_configured", "companion_not_configured"
    if request.companion_root is not None:
        try:
            _sources(request.companion_root)
            source_state, reason = "pinned_source_verified", "runtime_dependencies_and_recording_permissions_unqualified"
        except (OSError, ValueError) as error:
            source_state, reason = "unsupported", type(error).__name__
    ffmpeg = shutil.which("ffmpeg")
    return LiveResult(operation="probe", status="observed", data={
        "platform": sys.platform, "ffmpeg_path": ffmpeg, "ffmpeg_executable_present": ffmpeg is not None,
        "ffmpeg_version_and_devices": "UNKNOWN_not_executed", "devices": devices,
        "companion_source": source_state, "companion_revision": REVISION,
        "capture_support": "unsupported" if sys.platform != "win32" or source_state != "pinned_source_verified" or not ffmpeg else "unqualified",
        "reason": "pinned_screen_window_capture_is_windows_gdigrab_only" if sys.platform != "win32" else reason,
        "recording_permission": "UNKNOWN_no_permission_request",
    }).model_dump()


def prepare_capture(request: CaptureRequest) -> dict:
    """Return an explicit operator handoff or unsupported state before output allocation."""
    state = probe(ProbeRequest(companion_root=request.companion_root))
    checked_path(request.output_dir)
    if state["data"]["capture_support"] == "unsupported":
        return LiveResult(operation="capture", status="unsupported", data=state["data"]).model_dump()
    return LiveResult(operation="capture", status="requires_operator_execution", data={
        "request": request.model_dump(), "entry_point": "python -m video_research_mcp.live_companion --record REQUEST.json",
        "source_entry_point": "watch_skill.loop.capture.capture_screen", "companion_revision": REVISION,
        "authority_basis": "explicit_caller_scope_not_principal_authentication",
        "runtime_dependencies": "UNKNOWN_until_separate_operator_launch",
    }).model_dump()


def run_capture(request: CaptureRequest) -> dict:
    """Execute only in a separately invoked operator process with explicit recording scope.

    The core MCP does not call this function. It never requests device grants,
    installs a runtime, or dispatches ASR/OCR/models. Native acceptance is separate.
    """
    import importlib

    prepared = prepare_capture(request)
    if prepared["status"] == "unsupported":
        return prepared
    root = _sources(request.companion_root)
    sys.path.insert(0, str(root / "src"))
    try:
        module = importlib.import_module("watch_skill.loop.capture")
    except ImportError:
        return LiveResult(operation="capture", status="unsupported", data={"reason": "companion_runtime_dependency_missing"}).model_dump()
    finally:
        sys.path.pop(0)
    if checked_path(module.__file__) != root / "src/watch_skill/loop/capture.py":
        raise PermissionError("Loaded companion capture module is not the pinned source")
    output = checked_path(request.output_dir)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    authority = request.authority
    captured = module.capture_screen(output, duration_seconds=authority.duration_seconds,
                                     window_title=authority.window_title)
    path = checked_path(str(captured.video_path))
    if not path.is_relative_to(output):
        raise PermissionError("Companion artifact escapes its owned output directory")
    raw = read_bytes(path, 8 * 1024 * 1024)
    if not raw:
        raise ValueError("Companion capture produced an empty artifact")
    return {"status": "captured_unqualified", "recording_started": True, "authority": authority.model_dump(),
            "artifact": {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)},
            "native_acceptance": "NOT_QUALIFIED", "provider_calls": 0}


def main() -> None:
    """Require an explicit operator recording invocation; there is no automatic retry."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true", required=True)
    parser.add_argument("request_file")
    args = parser.parse_args()
    request = CaptureRequest.model_validate_json(read_bytes(Path(args.request_file), MAX_ARCHIVE_BYTES))
    print(json.dumps(run_capture(request), ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
