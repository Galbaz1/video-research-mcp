"""Serve pinned original Qwen FreeCAD tools in one owned local GUI session.

The external unmodified MIT code retains © 2025 Shirokuma (k tanaka);
Qwen additions retain Apache-2.0 and the selected complete grants/notices.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import xmlrpc.client
from xml.sax.saxutils import escape

sys.dont_write_bytecode = True
_SCRIPT_DIR = Path(__file__).resolve().parent
_HELPER_DIR = (_SCRIPT_DIR if (_SCRIPT_DIR / "blender_session.py").is_file()
               else Path(__file__).resolve().parents[2] / "blender/scripts")
sys.path[:0] = [str(_SCRIPT_DIR), str(_HELPER_DIR)]
from blender_session import DIRECT_PACKAGES as DIRECT_PACKAGES  # noqa: E402
from blender_session import digest, runtime_report, shutdown  # noqa: E402
from freecad_jobs import JobMonitor, configure_specs  # noqa: E402

REVISION = "07736672525443c7f8a3f6405eed37d2236f023f"
PACKAGE = "src/capabilities/freecad/qwen_mm_plugins_freecad"
NATIVE = f"{PACKAGE}/vendor/FreeCADMCP/rpc_server"
TOOLS = frozenset("""
create_document create_object delete_object edit_object execute_code execute_code_async
get_object get_objects get_parts_list get_view insert_part_from_library list_documents
reload_document run_fem_analysis
""".split())
SOURCES = frozenset(
    [f"{PACKAGE}/{name}.py" for name in ("__init__", "__main__", "_responses", "loader")]
    + [f"{PACKAGE}/tools/{name}.py" for name in (*TOOLS, "__init__")]
    + [f"{NATIVE}/{name}.py" for name in (
        "__init__", "commands", "fem_executor", "gui_dispatch", "ip_filter", "object_factory",
        "parts_library", "property_mapper", "rpc_server", "serialize", "settings", "view_manager")]
    + ["src/mcp_framework.py"]
    + [f"src/shared/{name}.py" for name in (
        "__init__", "applaunch", "cache", "content", "env", "native_mode", "syscmd")]
)
GRANTS = frozenset(("LICENSE", "src/capabilities/freecad/NOTICE.md",
                    f"{PACKAGE}/vendor/FreeCADMCP/LICENSE"))
DEADLINE = 60


def admit_sources(root: Path, manifest: Path, manifest_sha256: str) -> dict:
    """Hash every selected source/grant and reject unadmitted discovery modules."""
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
                raise ValueError("Source escapes selected root")
            if path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
                raise ValueError(f"Source/grant hash mismatch: {row['path']}")
    for directory in (f"{PACKAGE}/tools", NATIVE):
        actual = {p.relative_to(root).as_posix() for p in (root / directory).iterdir()}
        if actual != {p for p in SOURCES if p.startswith(f"{directory}/")}:
            raise ValueError("Unadmitted modules present in a discovery directory")
    if len(data["expected_tools"]) != 14 or set(data["expected_tools"]) != TOOLS:
        raise ValueError("Tool selection differs from the original 14 tools")
    return data


def admit_binary(binary: Path, sha256: str) -> None:
    """Refuse a missing, nonexecutable or changed selected native executable."""
    if not binary.is_file() or not os.access(binary, os.X_OK) or digest(binary) != sha256:
        raise ValueError("Native executable/hash prerequisite failed")


def admit_native(data: dict, binary: Path, sha256: str) -> None:
    """Admit exact app and solver paths/bytes without executing any binary."""
    selected = data["selected_freecad"]
    if selected["version"] != "1.1.3" or sha256 != selected["sha256"]:
        raise ValueError("FreeCAD selection differs from the admitted descriptor")
    if binary.resolve() != Path(selected["path"]).resolve():
        raise ValueError("FreeCAD path differs from the selected direct native binary")
    admit_binary(binary, sha256)
    if set(data["selected_solvers"]) != {"ccx", "gmsh"}:
        raise ValueError("Selected solver closure must include exact ccx and gmsh")
    for solver in data["selected_solvers"].values():
        path = Path(solver["path"])
        if not path.is_absolute():
            raise ValueError("Solver path must be absolute")
        admit_binary(path, solver["sha256"])
        if path.stat().st_size != solver["bytes"]:
            raise ValueError("Solver size differs from the selected executable")


def prepare_session(output: Path) -> dict:
    """Create exclusive preexisting FreeCAD directories and an unused loopback port."""
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name in ("profile", "data", "tmp", "cwd", "jobs", "config", "cache"):
        (output / name).mkdir(mode=0o700)
    (output / "data" / "Mod").mkdir(mode=0o700)
    (output / "data" / "Macro").mkdir(mode=0o700)
    (output / "empty-config").write_text("")
    config = ('<?xml version="1.0" encoding="UTF-8"?><FCParameters><FCParamGroup Name="Root">'
              '<FCParamGroup Name="BaseApp"><FCParamGroup Name="Preferences">'
              '<FCParamGroup Name="Macro"><FCText Name="MacroPath">'
              f'{escape(str(output / "data/Macro"))}</FCText></FCParamGroup>'
              '</FCParamGroup></FCParamGroup></FCParamGroup></FCParameters>')
    (output / "profile/user.cfg").write_text(config)
    (output / "profile/system.cfg").write_text('<FCParameters><FCParamGroup Name="Root"/></FCParameters>')
    settings = {"remote_enabled": False, "allowed_ips": "127.0.0.1", "auto_start_rpc": False}
    (output / "data/freecad_mcp_settings.json").write_text(json.dumps(settings))
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    session_id = uuid.uuid4().hex
    name = f"VRM_{session_id}"
    return {"output": str(output), "data": str(output / "data"), "port": port,
            "session": session_id, "document": name,
            "document_path": str(output / "data" / f"{name}.FCStd")}


def session_environment(session: dict) -> dict:
    """Scrub credentials while preserving HOME/CODEX_HOME and owning native settings."""
    allowed = ("HOME", "CODEX_HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE",
               "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    output = Path(session["output"])
    env.update(PATH="/usr/bin:/bin", TMPDIR=str(output / "tmp"),
               FREECAD_USER_HOME=str(output / "profile"), FREECAD_USER_DATA=session["data"],
               FREECAD_USER_TEMP=str(output / "tmp"), FREECAD_RPC_HOST="127.0.0.1",
               FREECAD_RPC_PORT=str(session["port"]), FREECAD_MCP_HEADLESS="1",
               QWEN_MM_CONFIG=str(output / "empty-config"), QWEN_MM_CONFIG_DIR=str(output / "config"),
               QWEN_MM_CACHE=str(output / "cache"), QWEN_MM_NATIVE_MODE="1",
               QWEN_MM_AUTOLAUNCH="0", QWEN_MM_NO_AUTO_INSTALL="1",
               VRM_FREECAD_SESSION_FILE=str(output / "session.json"))
    return env


def native_environment(session: dict) -> dict:
    """Reproduce the selected macOS wrapper's bootstrap without its environment dump."""
    env = session_environment(session)
    prefix = Path(session["binary"]).parent.parent
    env.update(PREFIX=str(prefix), LD_LIBRARY_PATH=str(prefix / "lib"),
               PYTHONPATH=str(prefix), PYTHONHOME=str(prefix),
               FONTCONFIG_FILE="/etc/fonts/fonts.conf", FONTCONFIG_PATH="/etc/fonts",
               SSL_CERT_FILE=str(prefix / "ssl/cacert.pem"),
               GIT_SSL_CAINFO=str(prefix / "ssl/cacert.pem"))
    return env


def expected_identity(session: dict, pid: int) -> dict:
    """Bind the listener to the selected owned native process and session."""
    return {"pid": pid, "binary": session["binary"], "session": session["session"],
            "port": session["port"], "data": session["data"]}


def verify_identity(actual: dict, session: dict, process) -> None:
    """Reject stale/unrelated listeners and foreign documents or active selection."""
    expected = expected_identity(session, process.pid)
    if process.poll() is not None or any(actual.get(k) != v for k, v in expected.items()):
        raise ValueError("Identity is not the live owned FreeCAD session")
    docs = actual.get("documents")
    if docs not in ([], [session["document"]]):
        raise ValueError("Native document list escapes the owned session")
    if actual.get("active") != (session["document"] if docs else None):
        raise ValueError("Active native document is not the owned document")
    if any(name != session["document"] for name in actual.get("selection", [])):
        raise ValueError("Native selection belongs to another document")


class OwnedConnection:
    """Use one deadline-bounded loopback proxy; fatal timeouts cancel native work."""

    def __init__(self, session: dict, process, cleanup):
        self.session, self.process, self.cleanup = session, process, cleanup
        from http.client import HTTPConnection

        class Transport(xmlrpc.client.Transport):
            def make_connection(self, host):
                return HTTPConnection(host, timeout=DEADLINE)

        self.server = xmlrpc.client.ServerProxy(f"http://127.0.0.1:{session['port']}",
                                               allow_none=True, transport=Transport())

    def _call(self, method, *args):
        if self.process.poll() is not None:
            raise RuntimeError("Owned FreeCAD is no longer alive")
        try:
            result = getattr(self.server, method)(*args)
        except (OSError, TimeoutError, xmlrpc.client.ProtocolError):
            self.cleanup()
            raise
        if isinstance(result, dict) and "timed out" in str(result.get("error", "")).lower():
            self.cleanup()
            raise TimeoutError("Native GUI dispatch timed out; owned process reaped")
        return result

    def __getattr__(self, method):
        return lambda *args: self._call(method, *args)


def wait_ready(session: dict, process, cleanup, timeout: float = DEADLINE) -> None:
    """Require startup identity and a real GUI-dispatched identity on the owned RPC."""
    deadline = time.monotonic() + timeout
    receipt = Path(session["output"]) / "ready.json"
    connection = OwnedConnection(session, process, cleanup)
    timer = threading.Timer(timeout, cleanup)
    timer.start()
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Owned FreeCAD exited; inspect native.log")
            if receipt.exists():
                verify_identity(json.loads(receipt.read_text()), session, process)
                verify_identity(connection.vrm_identity(), session, process)
                return
            time.sleep(0.05)
        raise TimeoutError("FreeCAD startup exceeded 60 seconds; inspect native.log")
    finally:
        timer.cancel()
        timer.join()


def serve(session: dict, process, cleanup) -> None:
    """Serve original external specs plus the explicit owned job completion tool."""
    admit_sources(Path(session["source_root"]), Path(session["manifest"]), session["manifest_sha256"])
    root = Path(session["source_root"])
    sys.path[:0] = [str(root / "src"), str(root / "src/capabilities/freecad")]
    package = importlib.import_module("qwen_mm_plugins_freecad")
    framework = importlib.import_module("mcp_framework")
    loader = importlib.import_module("qwen_mm_plugins_freecad.loader")
    if len(package.SPECS) != 14 or {spec.name for spec in package.SPECS} != TOOLS:
        raise ValueError("Actual discovery differs from the admitted 14 original tools")
    loader._connection = OwnedConnection(session, process, cleanup)
    monitor = JobMonitor(session, process, cleanup)
    from blender_stdio import eof_transport

    try:
        specs = configure_specs(package.SPECS, framework, loader._connection, session, process,
                                cleanup, monitor, verify_identity)
        framework.serve("qwen-mm-plugins-freecad", package.__version__, specs,
                        transport=eof_transport(cleanup))
    finally:
        cleanup()
        monitor.close()


def run_session(args, data: dict) -> None:
    """Launch once and kill/reap the owned native group on EOF, error or signal."""
    session = prepare_session(args.output.resolve())
    session.update(binary=str(args.freecad.resolve()), binary_sha256=args.freecad_sha256,
                   source_root=str(args.source_root.resolve()), manifest=str(args.manifest.resolve()),
                   manifest_sha256=args.manifest_sha256, solvers=data["selected_solvers"])
    output = Path(session["output"])
    (output / "session.json").write_text(json.dumps(session))
    startup = Path(__file__).with_name("freecad_startup.py").resolve()
    macro = output / "startup.FCMacro"
    macro.write_text(f"exec(compile(open({str(startup)!r}, 'rb').read(), {str(startup)!r}, 'exec'), "
                     f"{{'__name__': '__main__', '__file__': {str(startup)!r}}})\n")
    command = [session["binary"], "--user-cfg", str(output / "profile/user.cfg"),
               "--system-cfg", str(output / "profile/system.cfg"), str(macro)]
    env = session_environment(session)
    with (output / "native.log").open("wb") as log:
        process = subprocess.Popen(command, cwd=output / "cwd", env=native_environment(session),
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        close_lock = threading.Lock()
        closed = False
        def cleanup():
            nonlocal closed
            with close_lock:
                if not closed:
                    shutdown(process)
                    closed = True
        def interrupted(signum, frame):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            cleanup()
            raise SystemExit(128 + signum)
        previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            (output / "native-process.json").write_text(json.dumps({"pid": process.pid, "group": process.pid}))
            wait_ready(session, process, cleanup)
            os.environ.clear()
            os.environ.update(env)
            os.chdir(output / "cwd")
            tempfile.tempdir = None
            serve(session, process, cleanup)
        finally:
            cleanup()
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def main(argv=None) -> int:
    """Check exact prerequisites without side effects, or run the owned stdio route."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-root", "manifest", "freecad", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("manifest-sha256", "freecad-sha256"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        data = admit_sources(args.source_root, args.manifest, args.manifest_sha256)
        admit_native(data, args.freecad, args.freecad_sha256)
        report = runtime_report(data)
        if args.output.exists():
            raise ValueError("Session output already exists; choose a new directory")
        if args.check:
            print(json.dumps(report))
            return 0 if report["ready"] else 2
        if not report["ready"]:
            raise ValueError(f"External runtime prerequisites failed: {report}")
        run_session(args, data)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, TimeoutError) as error:
        print(f"FreeCAD session refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
