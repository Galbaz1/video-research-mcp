"""Cold admission and exact-source bootstrap with bounded inert stand-ins."""

import json
import os
from pathlib import Path
import py_compile
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import local_asr_launch as launch  # noqa: E402


def row(path):
    """Record exact regular bytes for synthetic admission."""
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": launch.file_digest(path)}


def save(path, data):
    """Write a fixture descriptor and return its independent pin."""
    path.write_text(json.dumps(data))
    return launch.file_digest(path)


def inventory(root, output, allowed):
    """Use the real population reader for inert fixture bytes."""
    save(output, launch.population(root, allowed))
    return str(output), launch.file_digest(output)


@pytest.fixture
def pinned(tmp_path):
    """Bind a sentinel interpreter plus complete synthetic base/runtime/model trees."""
    base, runtime = tmp_path / "base", tmp_path / "runtime"
    for p in (base / "bin", base / "lib/python3.12/lib-dynload", runtime / "bin", runtime / "lib/python3.12/site-packages"):
        p.mkdir(parents=True)
    marker = tmp_path / "started"
    real = base / "bin/python3.12"
    real.write_text(f"#!/bin/sh\nprintf '%s' \"$$\" > '{marker}'\nexec /bin/sleep 30\n")
    real.chmod(0o755)
    (runtime / "bin/python").symlink_to(real)
    selected = runtime / "bin/python3.12"
    selected.symlink_to("python")
    library = base / "lib/libpython3.12.dylib"
    library.write_bytes(b"inert library")
    (base / "lib/python3.12/os.py").write_text("# inert stdlib inventory\n")
    cfg = runtime / "pyvenv.cfg"
    cfg.write_text(f"home = {base / 'bin'}\ninclude-system-site-packages = false\n")
    site = runtime / "lib/python3.12/site-packages"
    (site / "_virtualenv.pth").write_bytes(b"import _virtualenv")
    (site / "package.py").write_text("# inert package\n")
    source = Path(launch.__file__).parent
    models = {}
    for name in ("en", "multilingual"):
        directory = tmp_path / name
        directory.mkdir()
        for filename in launch.MODEL_FILES:
            (directory / filename).write_bytes(b"inert model identity")
        models[name] = {"directory": str(directory), "repo": "fixture/" + name, "revision": "a" * 40,
                        "files": [dict(row(directory / filename), path=filename) for filename in sorted(launch.MODEL_FILES)]}
    paths = [str(base / "lib/python312.zip"), str(base / "lib/python3.12"), str(base / "lib/python3.12/lib-dynload")]
    r = {"python": str(selected), "python_sha256": launch.file_digest(real), "versions": {"python": "3.12.13"},
         "directory": str(runtime), "base_directory": str(base), "lineage": launch.link_lineage(selected),
         "libpython": row(library), "pyvenv": row(cfg), "stdlib_paths": paths, "site_packages": str(site),
         "absent_paths": [paths[0], str(base / "pyvenv.cfg"), str(base / "bin/pyvenv.cfg"), str(runtime / "bin/pyvenv.cfg")],
         "bytecode_policy": "complete-inventory", "pth_policy": "inactive-exact-virtualenv-only"}
    r["inventory"], r["inventory_sha256"] = inventory(runtime, tmp_path / "runtime.json", [runtime, base])
    r["base_inventory"], r["base_inventory_sha256"] = inventory(base, tmp_path / "base.json", [runtime, base])
    data = {"schema_version": 2, "protocol": launch.PROTOCOL, "sources": {name: row(source / f"local_asr_{name}.py") for name in ("launch", "service", "worker")},
            "runtime": r, "models": models}
    data.update(script_sha256=data["sources"]["service"]["sha256"], worker_sha256=data["sources"]["worker"]["sha256"])
    path = tmp_path / "descriptor.json"
    save(path, data)
    return path, data


@pytest.fixture
def isolated(monkeypatch):
    """Represent only required trusted-launch flags for pre-exec unit assertions."""
    monkeypatch.setattr(launch, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=1, no_site=1),
                        dont_write_bytecode=True, pycache_prefix=None, executable=sys.executable, stderr=sys.stderr))


@pytest.mark.parametrize("change", ["descriptor", "service", "worker", "launcher", "python", "libpython", "stdlib", "base_extra", "cold_prefix",
                                    "pyvenv", "link", "inventory", "runtime", "extra", "model_extra", "model_link", "model", "missing_model", "boolean_version", "fifo"])
def test_cold_drift_refuses_before_any_optional_process(pinned, isolated, monkeypatch, change):
    """GIVEN pinned bytes WHEN drift occurs THEN neither sentinel nor module can run."""
    path, data = pinned
    r = data["runtime"]
    expected = launch.file_digest(path)
    if change == "descriptor":
        path.write_text("{}")
    elif change in {"service", "worker", "launcher"}:
        data["sources"]["launch" if change == "launcher" else change]["sha256"] = "0" * 64
    elif change == "python":
        Path(r["lineage"]["realpath"]).write_text("changed")
    elif change == "libpython":
        Path(r["libpython"]["path"]).write_text("changed")
    elif change == "stdlib":
        (Path(r["stdlib_paths"][1]) / "os.py").write_text("changed")
    elif change == "base_extra":
        (Path(r["base_directory"]) / "extra").write_text("changed")
    elif change == "cold_prefix":
        Path(r["absent_paths"][0]).write_text("changed")
    elif change == "pyvenv":
        Path(r["pyvenv"]["path"]).write_text("changed")
    elif change == "link":
        selected = Path(r["python"])
        selected.unlink()
        selected.symlink_to(Path(r["lineage"]["realpath"]))
    elif change == "inventory":
        r["inventory_sha256"] = "0" * 64
    elif change in {"runtime", "extra"}:
        (Path(r["site_packages"]) / ("package.py" if change == "runtime" else "extra.pyc")).write_bytes(b"changed")
    elif change in {"model", "model_extra", "model_link"}:
        directory = Path(data["models"]["en"]["directory"])
        if change == "model_link":
            (directory / "link").symlink_to(directory / "model.bin")
        else:
            (directory / ("model.bin" if change == "model" else "extra")).write_bytes(b"changed")
    elif change == "missing_model":
        data["models"].pop("en")
    elif change == "fifo":
        os.mkfifo(Path(r["site_packages"]) / "pipe")
    else:
        data["schema_version"] = True
    if change != "descriptor":
        expected = save(path, data)
    monkeypatch.setattr(launch.os, "execve", lambda *args: pytest.fail("optional process started"))
    assert launch.main(["--descriptor", str(path), "--expected-descriptor-sha256", expected]) == 2
    assert not (path.parent / "started").exists()


@pytest.mark.parametrize("hook", ["sitecustomize.py", "usercustomize.pyc", "extra.pth", "_virtualenv.pth"])
def test_even_inventoried_unqualified_startup_hooks_refused(pinned, hook):
    path, data = pinned
    r = data["runtime"]
    (Path(r["site_packages"]) / hook).write_text("# inert unqualified hook\n")
    r["inventory"], r["inventory_sha256"] = inventory(Path(r["directory"]), path.parent / "runtime.json", [r["directory"], r["base_directory"]])
    with pytest.raises(ValueError, match="Startup|hook"):
        launch.admit(path, save(path, data))


def test_known_pth_is_admitted_as_inactive_bytes(pinned):
    path, data = pinned
    assert launch.admit(path, launch.file_digest(path)) == data


def test_dependency_bytecode_is_explicitly_inventoried(pinned):
    path, data = pinned
    r = data["runtime"]
    cached = Path(r["site_packages"]) / "opaque.pyc"
    cached.write_bytes(b"inert admitted bytecode stand-in")
    r["inventory"], r["inventory_sha256"] = inventory(Path(r["directory"]), path.parent / "runtime.json", [r["directory"], r["base_directory"]])
    expected = save(path, data)
    assert launch.admit(path, expected) == data
    cached.write_bytes(b"changed inert bytes")
    with pytest.raises(ValueError, match="inventory"):
        launch.admit(path, expected)


def test_pinned_home_alias_and_lib_dynload_path(pinned):
    """Admit the actual uv home-alias shape, and refuse a later link change."""
    path, data = pinned
    r = data["runtime"]
    alias = path.parent / "base-alias"
    alias.symlink_to(r["base_directory"], target_is_directory=True)
    executable = Path(r["directory"]) / "bin/python"
    executable.unlink()
    executable.symlink_to(alias / "bin/python3.12")
    r["lineage"] = launch.link_lineage(r["python"])
    cfg = Path(r["pyvenv"]["path"])
    cfg.write_text(f"home = {alias / 'bin'}\ninclude-system-site-packages = false\n")
    r["pyvenv"] = row(cfg)
    r["stdlib_paths"][2] = str(alias / "lib/python3.12/lib-dynload")
    r["inventory"], r["inventory_sha256"] = inventory(Path(r["directory"]), path.parent / "runtime.json", [r["directory"], r["base_directory"]])
    expected = save(path, data)
    assert launch.admit(path, expected) == data
    alias.unlink()
    # Preserve identical resolution while changing the literal pinned link target.
    alias.symlink_to(str(r["base_directory"]) + "/.", target_is_directory=True)
    with pytest.raises(ValueError, match="interpreter"):
        launch.admit(path, expected)


@pytest.mark.parametrize("change", ["path", "prefix", "base_prefix", "executable", "cache", "python_version", "package_version"])
def test_effective_bootstrap_refuses_before_entry_source(monkeypatch, change):
    """Bound effective optional settings independently of the pre-exec inventory."""
    runtime = {"stdlib_paths": list(sys.path), "site_packages": "/inert-site",
               "base_directory": sys.base_prefix, "lineage": {"realpath": str(Path(sys.executable).resolve())},
               "versions": {"python": sys.version.split()[0], "faster-whisper": "fixture", "ctranslate2": "fixture", "numpy": "fixture"}}
    fake = SimpleNamespace(flags=SimpleNamespace(isolated=1, no_site=1), dont_write_bytecode=True,
                           pycache_prefix=None, path=list(sys.path), executable=sys.executable,
                           prefix=sys.base_prefix, base_prefix=sys.base_prefix, version=sys.version)
    if change in {"prefix", "base_prefix", "executable"}:
        setattr(fake, change, "/changed")
    elif change == "path":
        fake.path.append("/changed")
    elif change == "cache":
        fake.pycache_prefix = "/changed"
    elif change == "python_version":
        fake.version = "0.0.0 fixture"
    else:
        runtime["versions"]["numpy"] = "changed"
    import importlib.metadata
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "fixture")
    monkeypatch.setattr(launch, "sys", fake)
    monkeypatch.setattr(launch, "admit", lambda *args: {"runtime": runtime})
    monkeypatch.setattr(launch, "load_source", lambda *args: pytest.fail("entry source executed"))
    with pytest.raises(ValueError, match="bootstrap|version"):
        launch.selected_bootstrap(["--descriptor", "/inert", "--expected-descriptor-sha256", "inert", "--check"], sys.executable)


@pytest.mark.parametrize("flag", ["isolated", "no_site", "dont_write_bytecode", "cache_prefix"])
def test_trusted_flags_are_required(pinned, isolated, monkeypatch, flag):
    path, _ = pinned
    if flag in {"isolated", "no_site"}:
        setattr(launch.sys.flags, flag, 0)
    elif flag == "cache_prefix":
        launch.sys.pycache_prefix = "/unadmitted"
    else:
        launch.sys.dont_write_bytecode = False
    monkeypatch.setattr(launch.os, "execve", lambda *args: pytest.fail("optional process started"))
    assert launch.main(["--descriptor", str(path), "--expected-descriptor-sha256", launch.file_digest(path)]) == 2


def test_exec_flags_and_sanitized_environment(pinned, isolated, monkeypatch):
    path, data = pinned
    monkeypatch.setenv("PYTHONPATH", "/untrusted")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/untrusted")
    monkeypatch.setenv("OPENAI_API_KEY", "inert-test-value")
    calls = []
    monkeypatch.setattr(launch.os, "chdir", lambda path: calls.append(path))
    def replace(executable, argv, env):
        calls.append((executable, argv, env))
        raise SystemExit(17)
    monkeypatch.setattr(launch.os, "execve", replace)
    with pytest.raises(SystemExit) as result:
        launch.main(["--descriptor", str(path), "--expected-descriptor-sha256", launch.file_digest(path), "--entry", "worker", "--check"])
    assert result.value.code == 17 and calls[0] == "/"
    executable, argv, env = calls[1]
    assert argv[:5] == [data["runtime"]["python"], "-I", "-S", "-B", "-c"] and executable == argv[0]
    assert not {"PYTHONPATH", "DYLD_LIBRARY_PATH", "OPENAI_API_KEY"} & env.keys()


def test_replacement_preserves_pid_and_joins(pinned, tmp_path):
    """Execute only a shell/sleep sentinel through real admission and exec replacement."""
    path, _ = pinned
    process = subprocess.Popen([sys.executable, "-I", "-S", "-B", launch.__file__, "--descriptor", str(path),
                                "--expected-descriptor-sha256", launch.file_digest(path)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        marker = tmp_path / "started"
        deadline = time.monotonic() + 5
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        assert marker.exists() and int(marker.read_text()) == process.pid
        process.terminate()
        assert process.wait(timeout=5) == -signal.SIGTERM
        with pytest.raises(ProcessLookupError):
            os.kill(process.pid, 0)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def test_source_drift_refused_before_module_execution(tmp_path):
    """A changed inert marker source must never execute even with a valid adjacent pyc."""
    source = tmp_path / "entry.py"
    marker = tmp_path / "marker"
    source.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    expected = row(source)
    py_compile.compile(str(source), doraise=True)
    source.write_text(source.read_text() + "# changed\n")
    with pytest.raises(ValueError, match="Pinned bytes changed"):
        launch.load_source("inert_asr_fixture", expected)
    assert not marker.exists()


@pytest.mark.parametrize("entry", ["service", "worker"])
def test_exact_source_excludes_shadows_pyc_and_pth(tmp_path, entry):
    """Run the actual optional bootstrap with inert entries and qualified path stand-ins."""
    site = tmp_path / "site"
    site.mkdir()
    hook = tmp_path / "hook"
    (site / "_virtualenv.pth").write_text("import _virtualenv\n")
    (site / "_virtualenv.py").write_text(f"from pathlib import Path\nPath({str(hook)!r}).touch()\n")
    for name in ("faster-whisper", "ctranslate2", "numpy"):
        dist = site / (name.replace("-", "_") + "-0.dist-info")
        dist.mkdir()
        (dist / "METADATA").write_text(f"Name: {name}\nVersion: fixture\n")
    sources = {}
    for name in ("worker", "service"):
        source = tmp_path / f"local_asr_{name}.py"
        source.write_text("raise RuntimeError('excluded cached stand-in')\n")
        py_compile.compile(str(source), cfile=str(source.with_suffix(".pyc")), doraise=True)
        source.write_text("def main():\n    raise RuntimeError('check must not call main')\n")
        sources[name] = row(source)
    shadow = tmp_path / "pathlib.py"
    shadow.write_text("raise RuntimeError('excluded source shadow')\n")
    code = (f"import sys,types; m=types.ModuleType('local_asr_launch'); m.__file__={launch.__file__!r}; "
            f"sys.modules[m.__name__]=m; exec(compile({Path(launch.__file__).read_bytes()!r},m.__file__,'exec'),m.__dict__); "
            f"r={{'stdlib_paths':list(sys.path),'site_packages':{str(site)!r},'lineage':{{'realpath':str(m.Path(sys.executable).resolve())}},"
            "'base_directory':sys.base_prefix,'versions':{'python':sys.version.split()[0],'faster-whisper':'fixture','ctranslate2':'fixture','numpy':'fixture'},'bytecode_policy':'complete-inventory'}; "
            f"m.admit=lambda *a: {{'runtime':r,'sources':{sources!r}}}; "
            f"m.selected_bootstrap(['--descriptor','/inert','--expected-descriptor-sha256','inert','--entry',{entry!r},'--check'],sys.executable)")
    result = subprocess.run([str(Path(sys.executable).resolve()), "-I", "-S", "-B", "-c", code], cwd=tmp_path,
                            env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(tmp_path)}, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr.decode()
    receipt = json.loads(result.stdout)
    assert receipt["entry"] == entry and receipt["pth_active"] is False and receipt["path"][-1] == str(site)
    assert not hook.exists() and receipt["model_libraries_imported"] is False


@pytest.mark.parametrize("entry", ["service", "worker"])
def test_direct_entry_is_refused(entry):
    result = subprocess.run([sys.executable, "-I", "-S", "-B", str(Path(launch.__file__).with_name(f"local_asr_{entry}.py"))],
                            capture_output=True, timeout=5)
    assert result.returncode != 0 and b"local_asr_launch.py" in result.stderr
