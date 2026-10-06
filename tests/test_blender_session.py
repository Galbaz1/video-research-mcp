"""Owned Blender session policy tests using source/process/native stubs only."""

from concurrent.futures import ThreadPoolExecutor
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import signal
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest


def load_script(name):
    """Load owned stdlib-only code without importing upstream source or Blender."""
    spec = spec_from_file_location(name, Path(__file__).parents[1] / "scripts" / f"{name}.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bs = load_script("blender_session")
startup = load_script("blender_startup")


@pytest.fixture
def selection(tmp_path):
    """Supply a complete synthetic closure with explicit selected byte hashes."""
    root = tmp_path / "source"
    rows = []
    for path in sorted(bs.SOURCES | bs.GRANTS):
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(f"# synthetic admission fixture: {path}\n")
        rows.append({"path": path, "sha256": bs.digest(file), "bytes": file.stat().st_size})
    data = {
        "schema_version": 1, "source_revision": bs.REVISION,
        "execution_sources": [row for row in rows if row["path"] in bs.SOURCES],
        "license_sources": [row for row in rows if row["path"] in bs.GRANTS],
        "expected_tools": sorted(bs.TOOLS), "selected_python": "3.12.13",
        "selected_direct_packages": bs.DIRECT_PACKAGES,
    }
    binary = tmp_path / "Blender"
    binary.write_text("synthetic binary; never executed")
    binary.chmod(0o700)
    data["selected_blender"] = {"sha256": bs.digest(binary)}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(data))
    args = ["--source-root", str(root), "--manifest", str(manifest),
            "--manifest-sha256", bs.digest(manifest), "--blender", str(binary),
            "--blender-sha256", bs.digest(binary), "--output", str(tmp_path / "session")]
    return SimpleNamespace(root=root, manifest=manifest, data=data, binary=binary, args=args)


def test_complete_source_closure_admitted(selection):
    """GIVEN the complete selection WHEN admitted THEN all 34 sources and grants match."""
    assert len(bs.SOURCES) == 34
    assert len(bs.GRANTS) == 3
    assert bs.admit_sources(selection.root, selection.manifest,
                            bs.digest(selection.manifest)) == selection.data


@pytest.mark.parametrize("changed", ["source", "grant", "manifest", "binary"])
def test_hash_refusal_precedes_foreign_import(selection, monkeypatch, changed):
    """GIVEN changed admitted bytes WHEN selected THEN no foreign import or launch occurs."""
    if changed in ("source", "grant"):
        path = sorted(bs.SOURCES if changed == "source" else bs.GRANTS)[0]
        (selection.root / path).write_text("modified")
    elif changed == "manifest":
        selection.manifest.write_text("{}")
    else:
        selection.binary.write_text("modified binary")
    monkeypatch.setattr(bs.importlib, "import_module", lambda *a: pytest.fail("foreign import"))
    monkeypatch.setattr(bs.subprocess, "Popen", lambda *a, **k: pytest.fail("native launch"))
    assert bs.main(selection.args) == 2


@pytest.mark.parametrize("mutation", ["revision", "missing_source", "missing_grant", "extra_tool"])
def test_descriptor_selection_refused(selection, mutation):
    """GIVEN incomplete or expanded closure WHEN admitted THEN selection fails."""
    if mutation == "revision":
        selection.data["source_revision"] = "0" * 40
    elif mutation == "missing_source":
        selection.data["execution_sources"].pop()
    elif mutation == "missing_grant":
        selection.data["license_sources"].pop()
    else:
        extra = selection.root / bs.PACKAGE / "tools" / "unread.py"
        extra.write_text("raise Exception('must not import')")
    selection.manifest.write_text(json.dumps(selection.data))
    with pytest.raises(ValueError):
        bs.admit_sources(selection.root, selection.manifest, bs.digest(selection.manifest))


def test_other_correctly_hashed_binary_cannot_override_selection(selection, monkeypatch):
    """GIVEN an alternate executable with its real hash WHEN selected THEN it is refused."""
    selection.binary.write_text("alternate but correctly caller-hashed executable")
    args = list(selection.args)
    args[args.index("--blender-sha256") + 1] = bs.digest(selection.binary)
    monkeypatch.setattr(bs.importlib, "import_module", lambda *a: pytest.fail("foreign import"))
    monkeypatch.setattr(bs.subprocess, "Popen", lambda *a, **k: pytest.fail("native launch"))
    assert bs.main(args) == 2


def test_existing_output_preserved(selection, monkeypatch):
    """GIVEN existing output WHEN selected THEN it is refused without overwrite."""
    output = Path(selection.args[-1])
    output.mkdir()
    keep = output / "keep"
    keep.write_text("original")
    monkeypatch.setattr(bs, "runtime_report", lambda data: {"ready": True})
    monkeypatch.setattr(bs, "run_session", lambda *a: pytest.fail("launch"))
    assert bs.main(selection.args) == 2
    assert keep.read_text() == "original"


def test_check_is_read_only(selection, monkeypatch, capsys):
    """GIVEN selected prerequisites WHEN checking THEN no session or foreign code starts."""
    monkeypatch.setattr(bs, "runtime_report", lambda data: {"ready": True})
    monkeypatch.setattr(bs.importlib, "import_module", lambda *a: pytest.fail("foreign import"))
    monkeypatch.setattr(bs.subprocess, "Popen", lambda *a, **k: pytest.fail("native launch"))
    assert bs.main(selection.args + ["--check"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ready": True}
    assert not Path(selection.args[-1]).exists()


def test_runtime_metadata_only(selection, monkeypatch):
    """GIVEN wrong runtime WHEN checked THEN actionable prerequisites are returned."""
    monkeypatch.setattr(bs.importlib.metadata, "version", lambda name: bs.DIRECT_PACKAGES[name])
    monkeypatch.setattr(bs.platform, "python_version", lambda: "3.11.0")
    report = bs.runtime_report(selection.data)
    assert not report["ready"]
    assert report["packages"] == bs.DIRECT_PACKAGES
    assert "external Python with -I" in report["hint"]


def test_credential_scrub_preserves_home_and_owns_profile(tmp_path, monkeypatch):
    """GIVEN ambient secrets/settings WHEN preparing THEN only allowed context survives."""
    monkeypatch.setenv("HOME", "/original/home")
    monkeypatch.setenv("CODEX_HOME", "/original/codex")
    for name in ("DASHSCOPE_API_KEY", "BLENDERMCP_SKETCHFAB_API_KEY", "PYTHONPATH",
                 "QWEN_MM_CONFIG_DIR", "FASTMCP_PORT", "HTTP_PROXY"):
        monkeypatch.setenv(name, "must disappear")
    session = bs.prepare_session(tmp_path / "owned")
    env = bs.session_environment(session)
    assert env["HOME"] == "/original/home"
    assert env["CODEX_HOME"] == "/original/codex"
    assert not any(name in env for name in ("DASHSCOPE_API_KEY", "PYTHONPATH", "HTTP_PROXY"))
    assert env["BLENDER_HOST"] == "127.0.0.1"
    assert env["BLENDER_PORT"] == str(session["port"])
    assert env["QWEN_MM_AUTOLAUNCH"] == "0"
    assert env["QWEN_MM_NO_AUTO_INSTALL"] == "1"
    assert env["QWEN_MM_NATIVE_MODE"] == "1"
    assert Path(env["QWEN_MM_CONFIG"]).read_text() == ""
    assert Path(env["TMPDIR"]).parent == tmp_path / "owned"
    assert Path(env["BLENDER_USER_CONFIG"]).is_dir()
    assert list((tmp_path / "owned" / "cwd").iterdir()) == []


@pytest.fixture
def native_stub():
    """Model register's default autostart and scene/preferences without bpy imports."""
    class Scene(dict):
        pass

    scene = Scene()
    preferences = SimpleNamespace(hyper3d_api_key="secret", sketchfab_api_key="secret")
    bpy = SimpleNamespace(context=SimpleNamespace(
        scene=scene, preferences=SimpleNamespace(addons={"owned": SimpleNamespace(
            preferences=preferences)})), types=SimpleNamespace())
    starts = []

    class Server:
        def __init__(self, host="localhost", port=9876):
            self.host, self.port, self.running = host, port, False
            self.socket = SimpleNamespace(getsockname=lambda: (host, port))

        def start(self):
            starts.append((self.host, self.port))
            self.running = True

    def register():
        scene.blendermcp_auto_start_server = True
        scene.blendermcp_port = 9876
        bpy.types.blendermcp_server = Server()
        bpy.types.blendermcp_server.start()

    addon = SimpleNamespace(BlenderMCPServer=Server, register=register)
    requests = SimpleNamespace(Session=type("Session", (), {"send": lambda *a: "network"}))
    session = {"session": "identity", "port": 12345}
    return SimpleNamespace(addon=addon, bpy=bpy, requests=requests, starts=starts,
                           session=session, preferences=preferences)


def test_native_registration_suppresses_default_and_denies_providers(native_stub):
    """GIVEN source autostart WHEN registering THEN only owned listener and disabled state exist."""
    n = native_stub
    original = n.addon.BlenderMCPServer.start
    server = startup.initialize(n.addon, n.bpy, n.requests, n.session)
    assert n.starts == [("127.0.0.1", 12345)]
    assert n.addon.BlenderMCPServer.start is original
    scene = n.bpy.context.scene
    assert not scene.blendermcp_auto_start_server
    assert all(getattr(scene, name) is False for name in bs.FLAGS)
    assert all(getattr(scene, name) == "" for name in bs.CREDENTIALS)
    assert scene["vrm_session"] == "identity"
    assert scene.blendermcp_port == 12345
    assert scene.blendermcp_server_running is True
    assert n.bpy.types.blendermcp_server is server
    assert n.preferences.hyper3d_api_key == n.preferences.sketchfab_api_key == ""
    with pytest.raises(RuntimeError, match="transport is disabled"):
        n.requests.Session().send(None)


def test_start_method_restored_after_registration_error(native_stub):
    """GIVEN register failure WHEN suppressed THEN the original start method is restored."""
    n = native_stub
    original = n.addon.BlenderMCPServer.start
    n.addon.register = lambda: (_ for _ in ()).throw(ValueError("registration failed"))
    with pytest.raises(ValueError, match="registration failed"):
        startup.initialize(n.addon, n.bpy, n.requests, n.session)
    assert n.addon.BlenderMCPServer.start is original


def test_requests_denial_receipt_omits_sensitive_url_fields(tmp_path, monkeypatch):
    """GIVEN a denied request WHEN recorded THEN only method, scheme and host survive."""
    log = tmp_path / "requests-denied.jsonl"
    log.write_text("")
    monkeypatch.setattr(startup, "DENIAL_LOG", log)
    request = SimpleNamespace(method="POST", url="https://user:secret@example.test/path?key=secret")
    with pytest.raises(RuntimeError, match="transport is disabled"):
        startup.deny_requests(object(), request, data="private payload")
    assert json.loads(log.read_text()) == {"method": "POST", "scheme": "https", "host": "example.test"}
    assert "secret" not in log.read_text() and "private" not in log.read_text()


def test_full_handlers_serialized(tmp_path):
    """GIVEN concurrent screenshot calls WHEN wrapped THEN file read/delete stays serialized."""
    shared = tmp_path / "same-screenshot.png"
    active = 0
    maximum = 0
    admissions = []

    def handler(arguments):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        shared.write_text(arguments["value"])
        time.sleep(0.015)
        result = shared.read_text()
        shared.unlink()
        active -= 1
        return result

    specs = [SimpleNamespace(handle=handler), SimpleNamespace(handle=handler)]
    bs.serialize_specs(specs, lambda: admissions.append(threading.get_ident()))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(specs[i % 2].handle, {"value": str(i)}) for i in range(6)]
        assert [f.result() for f in futures] == [str(i) for i in range(6)]
    assert maximum == 1
    assert len(admissions) == 6
    assert not shared.exists()


@pytest.mark.parametrize("field,value", [("pid", 888), ("session", "old"),
                                        ("binary", "/other/Blender"), ("port", 9876)])
def test_wrong_readiness_identity_refused(tmp_path, monkeypatch, field, value):
    """GIVEN an unrelated/stale listener WHEN admitting THEN it cannot count as readiness."""
    session = {"output": str(tmp_path), "binary": "/selected/Blender",
               "session": "owned", "port": 12345}
    process = SimpleNamespace(pid=777, poll=lambda: None)
    receipt = bs.expected_identity(session, process.pid)
    (tmp_path / "ready.json").write_text(json.dumps(receipt))
    actual = receipt | {field: value}
    monkeypatch.setattr(bs, "socket_identity", lambda port, deadline: actual)
    with pytest.raises(ValueError, match="not the live owned"):
        bs.wait_ready(session, process)


def test_dead_native_refused(tmp_path):
    """GIVEN exited owned process WHEN admitting THEN open ports cannot establish readiness."""
    with pytest.raises(RuntimeError, match="exited"):
        bs.wait_ready({"output": str(tmp_path)}, SimpleNamespace(poll=lambda: 1))


@pytest.mark.parametrize("times_out", [False, True])
def test_shutdown_owned_group_reaped(monkeypatch, times_out):
    """GIVEN the exact owned process WHEN closing THEN TERM/kill deadlines reap it."""
    signals, waits = [], []
    def wait(timeout):
        waits.append(timeout)
        if times_out and len(waits) == 1:
            raise subprocess.TimeoutExpired("Blender", timeout)
        return 0
    process = SimpleNamespace(pid=456, wait=wait)
    monkeypatch.setattr(bs.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    bs.shutdown(process)
    assert signals[0] == (456, signal.SIGTERM)
    assert all(pid == 456 for pid, _ in signals)
    assert signals[-1] == (456, signal.SIGKILL)
    assert waits == ([5, 5] if times_out else [5])


@pytest.mark.parametrize("failure", ["eof", "error", "sigterm"])
def test_stdio_terminal_paths_cleanup_owned_native(selection, monkeypatch, failure):
    """GIVEN an owned launched session WHEN serving ends THEN native cleanup always runs."""
    cleanup, commands, signals = [], [], {}
    process = SimpleNamespace(pid=456)
    def popen(command, **kwargs):
        commands.append((command, kwargs))
        return process
    def serve(session, child):
        if failure == "error":
            raise RuntimeError("MCP failed")
        if failure == "sigterm":
            signals[signal.SIGTERM](signal.SIGTERM, None)
    monkeypatch.setattr(bs.subprocess, "Popen", popen)
    monkeypatch.setattr(bs, "wait_ready", lambda *a: None)
    monkeypatch.setattr(bs, "serve", serve)
    monkeypatch.setattr(bs, "shutdown", lambda child: cleanup.append(child))
    monkeypatch.setattr(bs.signal, "signal", lambda sig, fn: signals.setdefault(sig, fn))
    monkeypatch.setattr(bs.os, "environ", dict(bs.os.environ))
    monkeypatch.setattr(bs.os, "chdir", lambda path: None)
    monkeypatch.setattr(bs.tempfile, "tempdir", None)
    args = SimpleNamespace(output=Path(selection.args[-1]), source_root=selection.root,
                           manifest=selection.manifest, manifest_sha256=bs.digest(selection.manifest),
                           blender=selection.binary, blender_sha256=bs.digest(selection.binary))
    if failure == "eof":
        bs.run_session(args)
    else:
        with pytest.raises(RuntimeError if failure == "error" else SystemExit):
            bs.run_session(args)
    assert json.loads((args.output / "native-process.json").read_text()) == {
        "pid": process.pid, "group": process.pid}
    assert cleanup and all(child is process for child in cleanup)
    if failure == "sigterm":
        assert cleanup[0] is process
    command, kwargs = commands[0]
    assert all(flag in command for flag in ("--offline-mode", "--disable-autoexec", "--factory-startup"))
    assert "--background" not in command and "-b" not in command
    assert kwargs["cwd"] == args.output / "cwd"
    assert kwargs["start_new_session"] is True
    assert kwargs["stdout"].name == str(args.output / "native.log")


def test_serving_uses_transport_that_owns_eof_cleanup(tmp_path, monkeypatch):
    """GIVEN original framework serving WHEN wired THEN EOF owns native cleanup."""
    specs = [SimpleNamespace(name=name, handle=lambda args: []) for name in bs.TOOLS]
    seen = {}
    package = SimpleNamespace(SPECS=specs, __version__="1.1.0")
    def framework_serve(*args, transport=None):
        seen["transport"] = transport
        assert callable(transport), "Native cleanup must start at transport EOF"
    modules = {
        "qwen_mm_plugins_blender": package,
        "mcp_framework": SimpleNamespace(serve=framework_serve),
        "qwen_mm_plugins_blender.loader": SimpleNamespace(),
    }
    monkeypatch.setattr(bs, "importlib", SimpleNamespace(import_module=modules.__getitem__))
    bs.serve({"source_root": str(tmp_path)}, SimpleNamespace(pid=456))
    assert callable(seen["transport"])


async def test_eof_cleanup_precedes_shielded_worker_join():
    """GIVEN a shielded native worker WHEN input closes THEN cleanup precedes join."""
    import anyio
    from blender_stdio import forward_input

    started, release, cleaned, returned = (threading.Event() for _ in range(4))
    source_sender, source_receiver = anyio.create_memory_object_stream(0)
    target_sender, target_receiver = anyio.create_memory_object_stream(0)
    def blocked_native():
        started.set()
        release.wait(5)
        returned.set()
    def cleanup():
        cleaned.set()
    async def worker():
        await anyio.to_thread.run_sync(blocked_native)
    try:
        async with anyio.create_task_group() as group:
            group.start_soon(worker)
            group.start_soon(forward_input, source_receiver, target_sender, cleanup)
            with anyio.fail_after(1):
                while not started.is_set():
                    await anyio.sleep(0.01)
            await source_sender.aclose()
            with anyio.fail_after(1):
                while not cleaned.is_set():
                    await anyio.sleep(0.01)
            assert not returned.is_set()
            with pytest.raises(anyio.EndOfStream):
                await target_receiver.receive()
            release.set()
    finally:
        release.set()
        await source_receiver.aclose()
        await target_receiver.aclose()
    assert returned.is_set()


def test_isolated_interpreter_can_resolve_owned_transport(tmp_path):
    """GIVEN Python -I without script path WHEN serving THEN owned helper resolves."""
    import sys
    script = Path(__file__).parents[1] / "scripts/blender_session.py"
    code = f'''
import importlib.util,sys
from types import SimpleNamespace
import anyio,mcp.server.stdio
spec=importlib.util.spec_from_file_location("isolated_owned_session",{str(script)!r})
bs=importlib.util.module_from_spec(spec);spec.loader.exec_module(bs)
specs=[SimpleNamespace(name=n,handle=lambda a:[]) for n in bs.TOOLS]
def serve(*args,transport=None):
 assert callable(transport)
modules={{"qwen_mm_plugins_blender":SimpleNamespace(SPECS=specs,__version__="1.1.0"),
"mcp_framework":SimpleNamespace(serve=serve),
"qwen_mm_plugins_blender.loader":SimpleNamespace()}}
bs.importlib.import_module=modules.__getitem__
bs.serve({{"source_root":{str(tmp_path)!r}}},SimpleNamespace(pid=456))
assert sys.modules["blender_stdio"].__file__=={str(script.with_name('blender_stdio.py'))!r}
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.parametrize("expires_during", ["connect", "send", "recv"])
def test_socket_identity_uses_absolute_startup_deadline(tmp_path, monkeypatch, expires_during):
    """GIVEN a trickling fake socket THEN the existing absolute deadline stops read retries."""
    session = {"output": str(tmp_path), "binary": "/fake/Blender", "session": "owned", "port": 12345}
    process = SimpleNamespace(pid=777, poll=lambda: None)
    identity = bs.expected_identity(session, process.pid)
    (tmp_path / "ready.json").write_text(json.dumps(identity))
    clock, calls = [0.0], []
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            calls.append(("closed", clock[0]))
        def settimeout(self, timeout):
            calls.append(("timeout", timeout))
            assert 0 < timeout <= min(1, max(0, 1 - clock[0]))
        def sendall(self, request):
            calls.append(("send", clock[0]))
            if expires_during == "send":
                clock[0] = 1.0
        def recv(self, size):
            calls.append(("recv", clock[0]))
            if clock[0] >= 1:
                raise AssertionError("receive started after absolute startup deadline")
            clock[0] += .4
            assert size <= 8192
            return b" "
    def connect(address, timeout):
        calls.append(("connect", timeout))
        if expires_during == "connect":
            clock[0] = 1.0
        return Connection()
    monkeypatch.setattr(bs.socket, "create_connection", connect)
    monkeypatch.setattr(bs.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(bs.time, "sleep", lambda value: clock.__setitem__(0, clock[0] + value))
    with pytest.raises(TimeoutError, match="startup exceeded"):
        bs.wait_ready(session, process, timeout=1)
    assert len([c for c in calls if c[0] == "recv"]) <= 3
    assert calls[-1][0] == "closed"


@pytest.mark.parametrize("expired", [False, True])
def test_socket_identity_preserves_valid_identity_and_refuses_expired_connect(monkeypatch, expired):
    clock, calls = [1.0 if expired else 0.0], []
    identity = {"pid": 777, "session": "owned"}
    payload = json.dumps({"status": "success", "result": {"result": json.dumps(identity)}}).encode()
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            calls.append("closed")
        def settimeout(self, value):
            assert 0 < value <= 1 - clock[0]
        def sendall(self, request):
            clock[0] += .2
        def recv(self, size):
            clock[0] += .2
            return payload
    def connect(address, timeout):
        calls.append("connect")
        clock[0] += .2
        return Connection()
    monkeypatch.setattr(bs.socket, "create_connection", connect)
    monkeypatch.setattr(bs.time, "monotonic", lambda: clock[0])
    if expired:
        with pytest.raises(TimeoutError, match="startup deadline"):
            bs.socket_identity(12345, 1.0)
        assert calls == []
    else:
        assert bs.socket_identity(12345, 1.0) == identity
        assert calls == ["connect", "closed"]
