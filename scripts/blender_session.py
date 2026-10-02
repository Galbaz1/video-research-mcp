"""Serve the pinned Qwen Blender tools in an explicitly owned local GUI session.

The upstream addon/tools remain unmodified and external. Their MIT attribution
is © 2025 Siddharth Ahuja; Qwen additions are Apache-2.0. See the admitted grants.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from functools import wraps

sys.dont_write_bytecode = True

REVISION = "07736672525443c7f8a3f6405eed37d2236f023f"
PACKAGE = "src/capabilities/blender/qwen_mm_plugins_blender"
TOOLS = frozenset("""
download_polyhaven_asset download_sketchfab_model execute_blender_code
generate_hunyuan3d_model generate_hyper3d_model_via_images
generate_hyper3d_model_via_text get_hunyuan3d_status get_hyper3d_status
get_object_info get_polyhaven_categories get_polyhaven_status get_scene_info
get_sketchfab_model_preview get_sketchfab_status get_viewport_screenshot
import_generated_asset import_generated_asset_hunyuan poll_hunyuan_job_status
poll_rodin_job_status search_polyhaven_assets search_sketchfab_models set_texture
""".split())
SOURCES = frozenset(
    [f"{PACKAGE}/{name}.py" for name in ("__init__", "__main__", "loader")]
    + [f"{PACKAGE}/tools/{name}.py" for name in (*TOOLS, "__init__")]
    + [f"{PACKAGE}/vendor/addon.py", "src/mcp_framework.py"]
    + [f"src/shared/{name}.py" for name in (
        "__init__", "env", "content", "native_mode", "applaunch", "syscmd")]
)
GRANTS = frozenset(("LICENSE", "src/capabilities/blender/NOTICE.md",
                    f"{PACKAGE}/vendor/LICENSE"))
DIRECT_PACKAGES = {"mcp": "1.30.0", "pillow": "11.3.0", "openai": "1.109.1",
                   "anyio": "4.15.1", "pydantic": "2.13.5", "docstring-parser": "0.18.0"}
FLAGS = tuple(f"blendermcp_use_{name}" for name in
              ("polyhaven", "hyper3d", "sketchfab", "hunyuan3d"))
CREDENTIALS = tuple(f"blendermcp_{name}" for name in (
    "hyper3d_api_key", "sketchfab_api_key", "hunyuan3d_secret_id",
    "hunyuan3d_secret_key", "hunyuan3d_api_url"))
IDENTITY_CODE = (
    "import json, os\ns = bpy.context.scene\nprint(json.dumps({"
    "'pid': os.getpid(), 'binary': os.path.realpath(bpy.app.binary_path), "
    "'session': s['vrm_session'], 'port': s.blendermcp_port, "
    f"'disabled': all(not getattr(s, n) for n in {FLAGS!r}), "
    f"'credentials_blank': all(not getattr(s, n) for n in {CREDENTIALS!r})"
    "}))"
)


def digest(path: Path) -> str:
    """Hash exact file bytes without loading foreign code."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def admit_sources(root: Path, manifest: Path, manifest_sha256: str) -> dict:
    """Admit the complete selected closure and grants before any foreign import."""
    if digest(manifest) != manifest_sha256:
        raise ValueError("Manifest hash differs from the trusted selection receipt")
    data = json.loads(manifest.read_text())
    if data["schema_version"] != 1 or data["source_revision"] != REVISION:
        raise ValueError("Manifest revision/schema is outside the selected profile")
    for key, expected in (("execution_sources", SOURCES), ("license_sources", GRANTS)):
        rows = data[key]
        if len(rows) != len(expected) or {row["path"] for row in rows} != expected:
            raise ValueError(f"Incomplete or unexpected {key}")
        for row in rows:
            path = (root / row["path"]).resolve()
            if not path.is_relative_to(root.resolve()):
                raise ValueError(f"Source escapes selection: {row['path']}")
            if path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
                raise ValueError(f"Source/grant hash mismatch: {row['path']}")
    tools = {p.relative_to(root).as_posix() for p in (root / PACKAGE / "tools").rglob("*.py")}
    if tools != {p for p in SOURCES if p.startswith(f"{PACKAGE}/tools/")}:
        raise ValueError("Unadmitted tool modules present in the discovery directory")
    if len(data["expected_tools"]) != 22 or set(data["expected_tools"]) != TOOLS:
        raise ValueError("Tool selection differs from the original 22 tools")
    return data


def admit_binary(binary: Path, sha256: str) -> None:
    """Refuse an absent, nonexecutable, or changed manually selected binary."""
    if not binary.is_file() or not os.access(binary, os.X_OK) or digest(binary) != sha256:
        raise ValueError("Blender executable/hash prerequisite failed")


def runtime_report(data: dict) -> dict:
    """Read installed metadata only; never import, install, or resolve dependencies."""
    if data["selected_python"] != "3.12.13" or data["selected_direct_packages"] != DIRECT_PACKAGES:
        raise ValueError("Runtime selection differs from the qualified external profile")
    versions = {}
    for name in DIRECT_PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    ready = platform.python_version() == data["selected_python"]
    ready = ready and versions == DIRECT_PACKAGES and bool(sys.flags.isolated)
    return {"ready": ready, "python": platform.python_version(), "packages": versions,
            "isolated": bool(sys.flags.isolated), "hint": "Use selected external Python with -I"}


def prepare_session(output: Path) -> dict:
    """Create an exclusive profile/config/cwd and unused loopback port."""
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name in ("profile", "tmp", "cwd", "scripts", "datafiles", "extensions"):
        (output / name).mkdir(mode=0o700)
    (output / "empty-config").write_text("")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    return {"output": str(output), "port": port, "session": uuid.uuid4().hex}


def session_environment(session: dict) -> dict:
    """Scrub ambient credentials/settings while preserving HOME and CODEX_HOME."""
    allowed = ("HOME", "CODEX_HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE",
               "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    output = Path(session["output"])
    env.update(PATH="/usr/bin:/bin", TMPDIR=str(output / "tmp"),
               BLENDER_USER_RESOURCES=str(output / "profile"),
               BLENDER_USER_CONFIG=str(output / "profile"),
               BLENDER_USER_SCRIPTS=str(output / "scripts"),
               BLENDER_USER_DATAFILES=str(output / "datafiles"),
               BLENDER_USER_EXTENSIONS=str(output / "extensions"),
               BLENDER_HOST="127.0.0.1", BLENDER_PORT=str(session["port"]),
               QWEN_MM_CONFIG=str(output / "empty-config"), QWEN_MM_NATIVE_MODE="1",
               QWEN_MM_AUTOLAUNCH="0", QWEN_MM_NO_AUTO_INSTALL="1")
    return env


def expected_identity(session: dict, pid: int) -> dict:
    """Bind readiness to the owned PID, binary, session, port and disabled integrations."""
    return {"pid": pid, "binary": session["binary"], "session": session["session"],
            "port": session["port"], "disabled": True, "credentials_blank": True}


def verify_identity(actual: dict, session: dict, process) -> None:
    """Reject exited children, unrelated listeners and stale startup receipts."""
    if process.poll() is not None or actual != expected_identity(session, process.pid):
        raise ValueError("Readiness identity is not the live owned Blender session")


def socket_identity(port: int) -> dict:
    """Read actual native identity over the selected loopback listener with a deadline."""
    with socket.create_connection(("127.0.0.1", port), timeout=1) as connection:
        connection.sendall(json.dumps({"type": "execute_code",
                                      "params": {"code": IDENTITY_CODE}}).encode())
        response = b""
        while len(response) < 65536:
            chunk = connection.recv(8192)
            if not chunk:
                raise ValueError("Native identity connection closed before response")
            response += chunk
            try:
                payload = json.loads(response)
            except json.JSONDecodeError:
                continue
            if payload.get("status") != "success":
                raise ValueError("Native identity command failed")
            return json.loads(payload["result"]["result"])
    raise ValueError("Native identity response exceeds the bounded receipt size")


def wait_ready(session: dict, process, timeout: float = 60) -> None:
    """Wait for startup and prove the listener belongs to the live child."""
    deadline = time.monotonic() + timeout
    receipt = Path(session["output"]) / "ready.json"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Owned Blender exited; inspect native.log")
        if receipt.exists():
            verify_identity(json.loads(receipt.read_text()), session, process)
            try:
                actual = socket_identity(session["port"])
            except (OSError, TimeoutError):
                time.sleep(0.1)
                continue
            verify_identity(actual, session, process)
            return
        time.sleep(0.1)
    raise TimeoutError("Blender startup exceeded 60 seconds; inspect native.log")


def shutdown(process, timeout: float = 5) -> None:
    """Terminate only the owned process group, then kill and reap within deadlines."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=timeout)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def serialize_specs(specs, admission) -> None:
    """Hold one shared lock through identity admission and complete handler return."""
    lock = threading.Lock()

    def wrap(handler):
        @wraps(handler)
        def handle(arguments):
            with lock:
                admission()
                return handler(arguments)
        return handle

    for spec in specs:
        spec.handle = wrap(spec.handle)


def serve(session: dict, process) -> None:
    """Import admitted original sources and serve their complete 22-tool registry."""
    root = Path(session["source_root"])
    sys.path[:0] = [str(Path(__file__).resolve().parent),
                    str(root / "src"), str(root / "src/capabilities/blender")]
    package = importlib.import_module("qwen_mm_plugins_blender")
    framework = importlib.import_module("mcp_framework")
    loader = importlib.import_module("qwen_mm_plugins_blender.loader")
    if len(package.SPECS) != 22 or {spec.name for spec in package.SPECS} != TOOLS:
        raise ValueError("Actual discovery differs from the admitted original tools")

    def admission():
        if process.poll() is not None:
            raise RuntimeError("Owned Blender is no longer alive")
        result = loader.get_connection().send_command("execute_code", {"code": IDENTITY_CODE})
        verify_identity(json.loads(result["result"]), session, process)

    serialize_specs(package.SPECS, admission)
    from blender_stdio import eof_transport

    framework.serve("qwen-mm-plugins-blender", package.__version__, package.SPECS,
                    transport=eof_transport(lambda: shutdown(process)))


def run_session(args) -> None:
    """Launch once, serve stdio, and clean up on EOF, errors, SIGINT or SIGTERM."""
    session = prepare_session(args.output.resolve())
    session.update(binary=str(args.blender.resolve()), binary_sha256=args.blender_sha256,
                   source_root=str(args.source_root.resolve()), manifest=str(args.manifest.resolve()),
                   manifest_sha256=args.manifest_sha256)
    output = Path(session["output"])
    (output / "session.json").write_text(json.dumps(session))
    env = session_environment(session)
    startup = Path(__file__).with_name("blender_startup.py").resolve()
    command = [session["binary"], "--offline-mode", "--disable-autoexec", "--factory-startup",
               "--python", str(startup), "--", "--session-file", str(output / "session.json")]
    with (output / "native.log").open("wb") as log:
        process = subprocess.Popen(command, cwd=output / "cwd", env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        closed = False
        def cleanup():
            nonlocal closed
            if not closed:
                closed = True
                shutdown(process)
        def interrupted(signum, frame):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            cleanup()
            raise SystemExit(128 + signum)
        previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            (output / "native-process.json").write_text(
                json.dumps({"pid": process.pid, "group": process.pid}))
            wait_ready(session, process)
            os.environ.clear()
            os.environ.update(env)
            os.chdir(output / "cwd")
            tempfile.tempdir = None
            serve(session, process)
        finally:
            cleanup()
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def main(argv=None) -> int:
    """Check prerequisites or start the explicitly selected stdio session."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--blender", type=Path, required=True)
    parser.add_argument("--blender-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        data = admit_sources(args.source_root, args.manifest, args.manifest_sha256)
        if args.blender_sha256 != data["selected_blender"]["sha256"]:
            raise ValueError("Blender hash differs from the admitted descriptor selection")
        admit_binary(args.blender, args.blender_sha256)
        report = runtime_report(data)
        if args.output.exists():
            raise ValueError("Session output already exists; choose a new directory")
        if args.check:
            print(json.dumps(report))
            return 0 if report["ready"] else 2
        if not report["ready"]:
            raise ValueError(f"External runtime prerequisites failed: {report}")
        run_session(args)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, TimeoutError) as error:
        print(f"Blender session refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
