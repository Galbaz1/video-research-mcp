"""Owned FreeCAD policy tests with synthetic source, process and native stubs."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest


def load_script(name):
    """Load owned stdlib code without importing FreeCAD or external Qwen source."""
    spec = spec_from_file_location(name, Path(__file__).parents[1] / "scripts" / f"{name}.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fs = load_script("freecad_session")
startup = load_script("freecad_startup")
jobs = load_script("freecad_jobs")
stdio = load_script("blender_stdio")


@pytest.fixture
def selection(tmp_path):
    """Build a complete synthetic selected closure and three fake native binaries."""
    root = tmp_path / "source"
    rows = []
    for relative in sorted(fs.SOURCES | fs.GRANTS):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# synthetic admission bytes {relative}\n")
        rows.append({"path": relative, "sha256": fs.digest(path), "bytes": path.stat().st_size})
    binaries = {}
    for name in ("freecad", "ccx", "gmsh"):
        binary = tmp_path / name
        binary.write_text(f"synthetic {name}; never execute")
        binary.chmod(0o700)
        binaries[name] = {"path": str(binary), "sha256": fs.digest(binary),
                          "bytes": binary.stat().st_size, "version": "1.1.3"}
    data = {"schema_version": 1, "source_revision": fs.REVISION,
            "execution_sources": [r for r in rows if r["path"] in fs.SOURCES],
            "license_sources": [r for r in rows if r["path"] in fs.GRANTS],
            "expected_tools": sorted(fs.TOOLS), "selected_python": "3.12.13",
            "selected_direct_packages": fs.DIRECT_PACKAGES,
            "selected_freecad": binaries["freecad"],
            "selected_solvers": {k: binaries[k] for k in ("ccx", "gmsh")}}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(data))
    args = ["--source-root", str(root), "--manifest", str(manifest),
            "--manifest-sha256", fs.digest(manifest), "--freecad", binaries["freecad"]["path"],
            "--freecad-sha256", binaries["freecad"]["sha256"], "--output", str(tmp_path / "session")]
    return SimpleNamespace(root=root, manifest=manifest, data=data, binaries=binaries, args=args)


def test_complete_source_and_native_admission(selection):
    """GIVEN all selected bytes WHEN admitted THEN the exact 39-source closure passes."""
    assert len(fs.SOURCES) == 39 and len(fs.GRANTS) == 3
    assert fs.admit_sources(selection.root, selection.manifest,
                            fs.digest(selection.manifest)) == selection.data
    fs.admit_native(selection.data, Path(selection.binaries["freecad"]["path"]),
                    selection.binaries["freecad"]["sha256"])


@pytest.mark.parametrize("changed", ["source", "grant", "manifest", "freecad", "ccx", "gmsh"])
def test_changed_bytes_refused_before_import_or_launch(selection, monkeypatch, changed):
    """GIVEN altered selected bytes WHEN invoked THEN no foreign/native execution occurs."""
    if changed in ("source", "grant"):
        relative = sorted(fs.SOURCES if changed == "source" else fs.GRANTS)[0]
        (selection.root / relative).write_text("changed")
    elif changed == "manifest":
        selection.manifest.write_text("{}")
    else:
        Path(selection.binaries[changed]["path"]).write_text("changed native bytes")
    monkeypatch.setattr(fs.importlib, "import_module", lambda *a: pytest.fail("foreign import"))
    monkeypatch.setattr(fs.subprocess, "Popen", lambda *a, **k: pytest.fail("native launch"))
    assert fs.main(selection.args) == 2
    assert not Path(selection.args[-1]).exists()


@pytest.mark.parametrize("directory,extra", [("tools", "unknown.py"), ("tools", "foreign.so"),
                                           ("tools", "foreign_package"), ("native", "unknown.py")])
def test_foreign_discovery_entries_refused(selection, directory, extra):
    """GIVEN a discovery expansion WHEN admitted THEN unrelated executable entries fail."""
    parent = selection.root / (fs.PACKAGE + "/tools" if directory == "tools" else fs.NATIVE)
    if extra == "foreign_package":
        (parent / extra).mkdir()
    else:
        (parent / extra).write_text("unadmitted")
    with pytest.raises(ValueError, match="Unadmitted"):
        fs.admit_sources(selection.root, selection.manifest, fs.digest(selection.manifest))


@pytest.mark.parametrize("key", ["execution_sources", "license_sources", "expected_tools"])
def test_incomplete_manifest_refused(selection, key):
    """GIVEN incomplete selection WHEN admitted THEN expanded caller hashes cannot fix it."""
    selection.data[key].pop()
    selection.manifest.write_text(json.dumps(selection.data))
    with pytest.raises(ValueError):
        fs.admit_sources(selection.root, selection.manifest, fs.digest(selection.manifest))


def test_check_is_read_only_and_existing_output_preserved(selection, monkeypatch, capsys):
    """GIVEN complete prerequisites WHEN checking THEN no imports, launch or output creation."""
    monkeypatch.setattr(fs, "runtime_report", lambda data: {"ready": True})
    monkeypatch.setattr(fs.importlib, "import_module", lambda *a: pytest.fail("foreign import"))
    monkeypatch.setattr(fs.subprocess, "Popen", lambda *a, **k: pytest.fail("native launch"))
    assert fs.main(selection.args + ["--check"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ready": True}
    output = Path(selection.args[-1])
    assert not output.exists()
    output.mkdir()
    (output / "keep").write_text("original")
    assert fs.main(selection.args + ["--check"]) == 2
    assert (output / "keep").read_text() == "original"


@pytest.mark.parametrize("layout", ["checkout", "wheel"])
def test_isolated_interpreter_explicitly_resolves_current_helpers(selection, tmp_path, layout):
    """GIVEN either current layout WHEN checked under -I THEN own helpers resolve without PYTHONPATH."""
    source = Path(__file__).parents[1] / "scripts"
    destination = tmp_path / ("checkout/scripts" if layout == "checkout" else "wheel/freecad/scripts")
    shared = destination if layout == "checkout" else destination.parents[1] / "blender/scripts"
    destination.mkdir(parents=True)
    shared.mkdir(parents=True, exist_ok=True)
    for name in ("freecad_session.py", "freecad_startup.py", "freecad_jobs.py"):
        shutil.copy2(source / name, destination / name)
    for name in ("blender_session.py", "blender_stdio.py"):
        shutil.copy2(source / name, shared / name)
    result = subprocess.run([sys.executable, "-I", "-B", str(destination / "freecad_session.py"),
                             *selection.args, "--check"], capture_output=True, text=True, timeout=5)
    assert result.returncode in (0, 2)
    assert json.loads(result.stdout)["isolated"] is True
    assert not Path(selection.args[-1]).exists()


def test_other_binary_path_cannot_replace_selected_native(selection):
    """GIVEN an identically hashed alternate path WHEN admitted THEN identity is refused."""
    selected = Path(selection.binaries["freecad"]["path"])
    other = selected.with_name("other")
    other.write_bytes(selected.read_bytes())
    other.chmod(0o700)
    with pytest.raises(ValueError, match="path differs"):
        fs.admit_native(selection.data, other, fs.digest(other))


@pytest.fixture
def owned(tmp_path):
    """Provide an owned empty session and a live synthetic process identity."""
    session = fs.prepare_session(tmp_path / "owned")
    session.update(binary=str(tmp_path / "FreeCAD.app/Contents/Resources/bin/freecad"),
                   solvers={k: {"path": str(tmp_path / k)} for k in ("ccx", "gmsh")})
    process = SimpleNamespace(pid=12345, poll=lambda: None)
    identity = {**fs.expected_identity(session, process.pid), "documents": [], "active": None,
                "selection": [], "document_path": ""}
    return SimpleNamespace(session=session, process=process, identity=identity)


def test_owned_environment_preserves_home_and_no_ambient_credentials(owned, monkeypatch):
    """GIVEN ambient credentials WHEN preparing THEN owned settings and home survive."""
    monkeypatch.setenv("HOME", "/original/home")
    monkeypatch.setenv("CODEX_HOME", "/original/codex")
    for key in ("DASHSCOPE_API_KEY", "PYTHONPATH", "HTTP_PROXY", "QWEN_MM_CONFIG", "FREECAD_RPC_HOST"):
        monkeypatch.setenv(key, "ambient-secret-or-setting")
    env = fs.session_environment(owned.session)
    assert env["HOME"] == "/original/home" and env["CODEX_HOME"] == "/original/codex"
    assert not any(key in env for key in ("DASHSCOPE_API_KEY", "PYTHONPATH", "HTTP_PROXY"))
    assert env["FREECAD_RPC_HOST"] == "127.0.0.1"
    assert env["FREECAD_RPC_PORT"] == str(owned.session["port"])
    assert env["QWEN_MM_NATIVE_MODE"] == "1" and env["QWEN_MM_AUTOLAUNCH"] == "0"
    assert env["QWEN_MM_NO_AUTO_INSTALL"] == "1"
    assert Path(env["QWEN_MM_CONFIG"]).read_text() == ""
    assert all(Path(env[key]).is_dir() for key in ("FREECAD_USER_HOME", "FREECAD_USER_DATA", "FREECAD_USER_TEMP"))
    native = fs.native_environment(owned.session)
    assert native["PYTHONHOME"] == str(Path(owned.session["binary"]).parent.parent)
    assert native["PYTHONPATH"] == native["PREFIX"] == native["PYTHONHOME"]
    settings = json.loads((Path(owned.session["data"]) / "freecad_mcp_settings.json").read_text())
    assert settings == {"remote_enabled": False, "allowed_ips": "127.0.0.1", "auto_start_rpc": False}


@pytest.mark.parametrize("mutation", ["pid", "binary", "session", "port", "data", "foreign_docs", "active", "selection"])
def test_identity_rejects_unrelated_listener_or_foreign_state(owned, mutation):
    """GIVEN mismatched native state WHEN admitted THEN no unrelated endpoint is accepted."""
    identity = dict(owned.identity)
    if mutation == "foreign_docs":
        identity["documents"] = ["foreign"]
    elif mutation == "selection":
        identity["selection"] = ["foreign"]
    else:
        identity[mutation] = "foreign"
    with pytest.raises(ValueError):
        fs.verify_identity(identity, owned.session, owned.process)


def test_readiness_requires_actual_gui_identity(owned, monkeypatch):
    """GIVEN a correct receipt but unrelated GUI RPC WHEN ready THEN admission fails."""
    (Path(owned.session["output"]) / "ready.json").write_text(json.dumps(owned.identity))
    other = {**owned.identity, "pid": 99999}
    monkeypatch.setattr(fs, "OwnedConnection", lambda *a: SimpleNamespace(vrm_identity=lambda: other))
    with pytest.raises(ValueError, match="live owned"):
        fs.wait_ready(owned.session, owned.process, lambda: None)


def test_startup_deadline_includes_slow_gui_identity(owned, monkeypatch):
    """GIVEN a queued identity call WHEN startup deadline expires THEN the owned child is closed."""
    (Path(owned.session["output"]) / "ready.json").write_text(json.dumps(owned.identity))
    killed = threading.Event()
    owned.process.poll = lambda: 1 if killed.is_set() else None
    def slow_identity():
        assert killed.wait(1)
        return owned.identity
    monkeypatch.setattr(fs, "OwnedConnection", lambda *a: SimpleNamespace(vrm_identity=slow_identity))
    with pytest.raises(ValueError, match="live owned"):
        fs.wait_ready(owned.session, owned.process, killed.set, timeout=0.03)
    assert killed.is_set()


def test_socket_and_native_gui_timeout_kill_and_reap(owned):
    """GIVEN a socket or uncancelled GUI timeout WHEN called THEN native cleanup precedes failure."""
    calls = []
    conn = fs.OwnedConnection(owned.session, owned.process, lambda: calls.append("reaped"))
    def timeout():
        raise TimeoutError("socket deadline")
    conn.server = SimpleNamespace(test=timeout)
    with pytest.raises(TimeoutError):
        conn._call("test")
    conn.server = SimpleNamespace(test=lambda: {"success": False, "error": "GUI dispatch timed out"})
    with pytest.raises(TimeoutError, match="reaped"):
        conn._call("test")
    assert calls == ["reaped", "reaped"]


def test_full_handler_lock_includes_readback_and_screenshot(owned):
    """GIVEN concurrent handlers WHEN invoked THEN admission and complete returns never overlap."""
    sequence = []
    def identity():
        sequence.append("identity")
        time.sleep(0.005)
        return owned.identity
    def handler(arguments):
        sequence.append(f"start-{arguments['n']}")
        time.sleep(0.02)
        sequence.append(f"screenshot-{arguments['n']}")
        return []
    class Spec:
        def __init__(self, name, description="", schema=None, model=None, handle=handler):
            self.name, self.handle = name, handle
    framework = SimpleNamespace(ToolSpec=Spec, tool_schema=lambda model: {})
    monitor = SimpleNamespace(pending=lambda: False)
    specs = jobs.configure_specs([Spec("execute_code")], framework,
                                SimpleNamespace(vrm_identity=identity), owned.session,
                                owned.process, lambda: None, monitor, fs.verify_identity)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(specs[0].handle, [{"n": 1}, {"n": 2}]))
    assert sequence in (["identity", "start-1", "screenshot-1", "identity", "identity", "start-2", "screenshot-2", "identity"],
                        ["identity", "start-2", "screenshot-2", "identity", "identity", "start-1", "screenshot-1", "identity"])


def test_complete_handler_deadline_reaps_before_late_result(owned, monkeypatch):
    """GIVEN a handler waiting past the deadline WHEN cleanup fires THEN late success is refused."""
    monkeypatch.setattr(jobs, "DEADLINE", 0.03)
    reaped = threading.Event()
    owned.process.poll = lambda: 1 if reaped.is_set() else None
    def handler(arguments):
        assert reaped.wait(1)
        return [{"type": "text", "text": "late success"}]
    class Spec:
        def __init__(self, name, description="", schema=None, model=None, handle=handler):
            self.name, self.handle = name, handle
    framework = SimpleNamespace(ToolSpec=Spec, tool_schema=lambda model: {})
    specs = jobs.configure_specs([Spec("execute_code")], framework,
                                SimpleNamespace(vrm_identity=lambda: owned.identity), owned.session,
                                owned.process, reaped.set, SimpleNamespace(pending=lambda: False), fs.verify_identity)
    with pytest.raises(ValueError, match="live owned"):
        specs[0].handle({"code": "trusted computation"})
    assert reaped.is_set()


def test_document_arguments_reload_and_part_containment(owned, tmp_path):
    """GIVEN foreign documents or escaped parts WHEN admitted THEN policy refuses before wire calls."""
    session = owned.session
    identity = {**owned.identity, "documents": [session["document"]], "active": session["document"]}
    with pytest.raises(ValueError, match="doc_name"):
        jobs.validate_arguments("get_object", {"doc_name": "foreign"}, identity, session)
    jobs.validate_arguments("create_document", {"name": session["document"]}, owned.identity, session)
    with pytest.raises(ValueError, match="empty"):
        jobs.validate_arguments("create_document", {"name": session["document"]}, identity, session)
    with pytest.raises(ValueError, match="saved"):
        jobs.validate_arguments("reload_document", {"doc_name": session["document"]}, identity, session)
    saved = Path(session["document_path"])
    saved.write_text("synthetic native document")
    jobs.validate_arguments("reload_document", {"doc_name": session["document"]},
                            {**identity, "document_path": str(saved)}, session)
    library = Path(session["data"]) / "Mod/parts_library"
    library.mkdir()
    part = library / "own.FCStd"
    part.write_text("synthetic")
    jobs.validate_arguments("insert_part_from_library", {"relative_path": "own.FCStd"}, identity, session)
    outside = tmp_path / "outside.FCStd"
    outside.write_text("outside")
    (library / "link.FCStd").symlink_to(outside)
    for relative in (str(outside), "../outside.FCStd", "link.FCStd", "missing.FCStd"):
        with pytest.raises(ValueError, match="contained"):
            jobs.validate_arguments("insert_part_from_library", {"relative_path": relative}, identity, session)


def test_native_configuration_and_loopback_startup(owned, monkeypatch):
    """GIVEN native stubs WHEN configuring THEN exact FEM paths and loopback are used."""
    values = {}
    class Param:
        def __init__(self, name):
            self.name = name
        def SetString(self, key, value):
            values[self.name + key] = value
        SetBool = SetInt = SetString
    app = SimpleNamespace(getUserAppDataDir=lambda: owned.session["data"], ParamGet=Param)
    workbenches = []
    gui = SimpleNamespace(activateWorkbench=workbenches.append)
    monkeypatch.setattr(startup.sys, "executable", owned.session["binary"])
    startup.configure_native(app, gui, owned.session)
    assert workbenches == ["PartWorkbench"]
    assert values["User parameter:BaseApp/Preferences/Mod/Fem/CcxccxBinaryPath"] == owned.session["solvers"]["ccx"]["path"]
    assert values["User parameter:BaseApp/Preferences/Mod/Fem/GeneralOverwriteSolverWorkingDirectory"] is False
    cache_clears = []
    parts = SimpleNamespace(get_parts_list=SimpleNamespace(cache_clear=lambda: cache_clears.append(True)))
    class RPC:
        def get_parts_list(self):
            return []
    rpc = SimpleNamespace(FreeCADRPC=RPC)
    def start(port):
        rpc.rpc_server_instance = SimpleNamespace(server_address=("127.0.0.1", port))
    rpc.start_rpc_server = start
    startup.install_owned_rpc(rpc, SimpleNamespace(dispatch_to_gui=lambda task, **kw: task()),
                              parts, app, gui, owned.session, SimpleNamespace(start=lambda code: {}))
    rpc.FreeCADRPC().get_parts_list()
    rpc.FreeCADRPC().get_parts_list()
    assert cache_clears == [True, True]


def test_native_gui_timeout_terminates_before_queued_mutation(owned, monkeypatch):
    """GIVEN stock dispatch timeout WHEN owned policy observes it THEN execution is terminal."""
    rpc = SimpleNamespace(FreeCADRPC=type("RPC", (), {}), start_rpc_server=lambda port: None,
                          rpc_server_instance=SimpleNamespace(server_address=("127.0.0.1", owned.session["port"])))
    dispatch = SimpleNamespace(dispatch_to_gui=lambda task, **kw: {"success": False, "error": "GUI dispatch timed out"})
    class NativeExit(BaseException):
        pass
    monkeypatch.setattr(startup.os, "_exit", lambda code: (_ for _ in ()).throw(NativeExit()))
    startup.install_owned_rpc(rpc, dispatch, None, None, None, owned.session, None)
    late = []
    with pytest.raises(NativeExit):
        rpc.dispatch_to_gui(lambda: late.append("mutated"))
    assert late == []
    assert json.loads((Path(owned.session["output"]) / "native-failure.json").read_text())["state"] == "timed_out"


def test_native_run_directory_reset_keeps_reported_solver_artifacts(owned):
    """GIVEN installed ccxtools run reset WHEN original temporary setup executes THEN artifact lineage survives."""
    class NativeSolver:
        def __init__(self):
            self.solver = SimpleNamespace(WorkingDir=str(Path(owned.session["output"]) / "cwd"))
        def setup_working_dir(self, param_working_dir=None, create=False):
            self.working_dir = param_working_dir or self.solver.WorkingDir
        def run(self):
            self.setup_working_dir()
            for suffix in (".inp", ".frd", ".dat"):
                (Path(self.working_dir) / ("fixture" + suffix)).write_text("actual stub output")
    ccxtools = SimpleNamespace(FemToolsCcx=NativeSolver)
    startup.bind_fem_working_directory(ccxtools, owned.session)
    fea = ccxtools.FemToolsCcx()
    reported = Path(owned.session["output"]) / "reported"
    reported.mkdir()
    fea.setup_working_dir(str(reported))
    fea.run()
    assert fea.working_dir == str(reported)
    assert {p.suffix for p in reported.iterdir()} == {".inp", ".frd", ".dat"}
    with pytest.raises(ValueError, match="owned"):
        fea.setup_working_dir("/tmp")


def test_cleanup_kills_owned_group_and_reaps_after_term_deadline(monkeypatch):
    """GIVEN stubborn owned native WHEN closing THEN TERM, KILL and reaping are bounded."""
    signals, waits = [], []
    monkeypatch.setattr(fs.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    def wait(timeout):
        waits.append(timeout)
        if len(waits) == 1:
            raise subprocess.TimeoutExpired("native", timeout)
    fs.shutdown(SimpleNamespace(pid=12345, wait=wait))
    assert waits == [5, 5]
    assert signals == [(12345, signal.SIGTERM), (12345, signal.SIGKILL), (12345, signal.SIGKILL)]


def test_launch_command_has_early_process_receipt_and_owned_bootstrap(selection, monkeypatch):
    """GIVEN a process stub WHEN launched THEN PID receipt precedes ready and final cleanup reaps once."""
    captured, order = {}, []
    process = SimpleNamespace(pid=12345, poll=lambda: None)
    monkeypatch.setattr(fs.os, "environ", {"HOME": "/original/home", "CODEX_HOME": "/original/codex"})
    monkeypatch.setattr(fs.os, "chdir", lambda path: captured.update(cwd=path))
    monkeypatch.setattr(fs.signal, "signal", lambda *args: "previous")
    monkeypatch.setattr(fs, "shutdown", lambda proc: order.append("reaped"))
    def popen(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return process
    def ready(session, child, cleanup):
        receipt = json.loads((Path(session["output"]) / "native-process.json").read_text())
        assert receipt == {"pid": child.pid, "group": child.pid}
        order.append("ready")
    monkeypatch.setattr(fs.subprocess, "Popen", popen)
    monkeypatch.setattr(fs, "wait_ready", ready)
    monkeypatch.setattr(fs, "serve", lambda *args: order.append("served"))
    args = SimpleNamespace(output=Path(selection.args[-1]), source_root=selection.root,
                           manifest=selection.manifest, manifest_sha256=fs.digest(selection.manifest),
                           freecad=Path(selection.binaries["freecad"]["path"]),
                           freecad_sha256=selection.binaries["freecad"]["sha256"])
    fs.run_session(args, selection.data)
    assert order == ["ready", "served", "reaped"]
    assert "--user-cfg" in captured["command"] and "--system-cfg" in captured["command"]
    assert "--safe-mode" not in captured["command"]
    assert captured["kwargs"]["start_new_session"] is True
    assert captured["kwargs"]["env"]["PYTHONHOME"] == str(args.freecad.parent.parent)
    assert fs.os.environ["HOME"] == "/original/home" and fs.os.environ["CODEX_HOME"] == "/original/codex"


def test_eof_native_cleanup_precedes_worker_stream_join():
    """GIVEN client EOF WHEN forwarded THEN native closure precedes output stream closure."""
    order = []
    async def incoming():
        if False:
            yield None
    class Outgoing:
        async def aclose(self):
            order.append("stream closed")
    asyncio.run(stdio.forward_input(incoming(), Outgoing(), lambda: order.append("native reaped")))
    assert order == ["native reaped", "stream closed"]


@pytest.mark.parametrize("operation", ["write", "replace"])
def test_fatal_dispatch_terminates_when_receipt_persistence_fails(owned, monkeypatch, operation):
    """GIVEN fatal GUI timeout plus receipt failure THEN exit is requested before propagation."""
    failure = OSError(f"receipt {operation} failed")
    exits = []
    rpc = SimpleNamespace(FreeCADRPC=type("RPC", (), {}), start_rpc_server=lambda port: None,
        rpc_server_instance=SimpleNamespace(server_address=("127.0.0.1", owned.session["port"])))
    dispatch = SimpleNamespace(dispatch_to_gui=lambda task, **kw: {"error": "GUI dispatch timed out"})
    monkeypatch.setattr(startup.os, "_exit", exits.append)
    startup.install_owned_rpc(rpc, dispatch, None, None, None, owned.session, None)
    def refused(*args, **kwargs):
        raise failure
    monkeypatch.setattr(Path, "write_text" if operation == "write" else "replace", refused)
    with pytest.raises(OSError) as caught:
        rpc.dispatch_to_gui(lambda: pytest.fail("queued work must not run"))
    assert caught.value is failure
    assert exits == [124]


def test_nonfatal_dispatch_returns_without_exit(owned, monkeypatch):
    exits = []
    rpc = SimpleNamespace(FreeCADRPC=type("RPC", (), {}), start_rpc_server=lambda port: None,
        rpc_server_instance=SimpleNamespace(server_address=("127.0.0.1", owned.session["port"])))
    result = {"success": True}
    dispatch = SimpleNamespace(dispatch_to_gui=lambda task, **kw: result)
    monkeypatch.setattr(startup.os, "_exit", exits.append)
    startup.install_owned_rpc(rpc, dispatch, None, None, None, owned.session, None)
    assert rpc.dispatch_to_gui(lambda: None) is result
    assert exits == []
