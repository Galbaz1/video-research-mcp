"""Stdlib-only admission and runtime clearance tests; foreign bytes never execute."""

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.test_spatial_inputs import build_inputs

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import spatial_session as ss  # noqa: E402


def isolated_sys(isolated):
    """Replace only the owned module reference, preserving real interpreter/test flags."""
    return SimpleNamespace(**{**vars(sys), "flags": SimpleNamespace(isolated=isolated)})


@pytest.fixture
def selection(tmp_path):
    """Create a complete synthetic source upper bound with explosive import sentinels."""
    root = tmp_path / "source"
    rows = []
    for relative in sorted(ss.SOURCES | ss.GRANTS):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("raise RuntimeError('FOREIGN SOURCE MUST NOT EXECUTE')\n")
        rows.append({"path": relative, "sha256": ss.digest(path), "bytes": path.stat().st_size})
    data = {"schema_version": 1, "source_revision": ss.REVISION,
            "execution_sources": [r for r in rows if r["path"] in ss.SOURCES],
            "license_sources": [r for r in rows if r["path"] in ss.GRANTS],
            "expected_tools": sorted(ss.TOOLS), "selected_python": "3.12.13",
            "selected_direct_packages": ss.DIRECT_PACKAGES, "runtime_clearance": "blocked-missing-font-grant",
            "runtime_fields": {"python_executable": None, "bootstrap_sources": []}}
    manifest = tmp_path / "descriptor.json"
    manifest.write_text(json.dumps(data))
    inputs, _, _ = build_inputs(tmp_path / "inputs")
    output = tmp_path / "output"
    argv = ["--source-root", str(root), "--manifest", str(manifest), "--manifest-sha256", ss.digest(manifest),
            "--inputs", str(inputs.manifest), "--inputs-sha256", inputs.sha256, "--output", str(output)]
    return SimpleNamespace(root=root, manifest=manifest, data=data, inputs=inputs, output=output, argv=argv)


def test_exact_static_upper_bound_and_tools(selection):
    assert len(ss.SOURCES) == 54 and len(ss.GRANTS) == 1 and len(ss.TOOLS) == 19
    assert ss.admit_sources(selection.root, selection.manifest, ss.digest(selection.manifest)) == selection.data


@pytest.mark.parametrize("changed", ["source", "grant", "manifest", "frame"])
def test_altered_bytes_refuse_without_foreign_import_or_output(selection, monkeypatch, changed):
    monkeypatch.setattr(ss, "sys", isolated_sys(True))
    monkeypatch.setattr(ss.importlib, "import_module", lambda *a: pytest.fail("foreign import"))
    if changed in ("source", "grant"):
        (selection.root / sorted(ss.SOURCES if changed == "source" else ss.GRANTS)[0]).write_text("changed")
    elif changed == "manifest":
        selection.manifest.write_text("{}")
    else:
        Path(next(iter(selection.inputs.frames))).write_bytes(b"changed")
    assert ss.main(selection.argv + ["--check"]) == 2
    assert not selection.output.exists()


@pytest.mark.parametrize("directory,entry", [("tools", "extra.py"), ("tools", "asset.so"), ("tools", "__pycache__"), ("experts", "other.py")])
def test_discovery_extra_entries_refuse(selection, directory, entry):
    path = selection.root / ss.PACKAGE / directory / entry
    path.mkdir() if entry == "__pycache__" else path.write_text("never import")
    with pytest.raises(ValueError, match="discovery"):
        ss.admit_sources(selection.root, selection.manifest, ss.digest(selection.manifest))


@pytest.mark.parametrize("change", ["missing", "duplicate", "unexpected", "tool", "revision", "symlink"])
def test_untrusted_closure_shape_refuses(selection, change):
    data = selection.data
    if change == "missing":
        data["execution_sources"].pop()
    elif change == "duplicate":
        data["execution_sources"][-1] = data["execution_sources"][0]
    elif change == "unexpected":
        data["execution_sources"][-1]["path"] = "foreign.py"
    elif change == "tool":
        data["expected_tools"][-1] = "invented"
    elif change == "revision":
        data["source_revision"] = "wrong"
    else:
        path = selection.root / data["execution_sources"][0]["path"]
        other = selection.root.parent / "outside.py"
        other.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(other)
    selection.manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        ss.admit_sources(selection.root, selection.manifest, ss.digest(selection.manifest))


def test_blocked_check_is_source_only_under_isolated_interpreter(selection):
    """GIVEN no selected runtime WHEN -I check runs THEN source bytes pass without output/import."""
    result = subprocess.run([sys.executable, "-I", "-B", ss.__file__, *selection.argv, "--check"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["sources_admitted"] and report["inputs_admitted"]
    assert report["source_files"] == 54 and report["frames"] == 3
    assert report["state"] == "source-only-runtime-blocked" and report["foreign_imports"] == 0
    assert not selection.output.exists()


def test_blocked_serving_stops_before_metadata_or_import(selection, monkeypatch):
    monkeypatch.setattr(ss.importlib, "import_module", lambda *a: pytest.fail("foreign import"))
    monkeypatch.setattr(ss.importlib.metadata, "version", lambda *a: pytest.fail("metadata lookup"))
    report = ss.runtime_report(selection.data)
    assert not report["ready"] and report["foreign_imports"] == 0
    args = SimpleNamespace(output=selection.output)
    with pytest.raises(ValueError, match="blocked"):
        ss.serve(args, selection.data, selection.inputs)
    assert not selection.output.exists()
    result = subprocess.run([sys.executable, "-I", "-B", ss.__file__, *selection.argv], capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and "Runtime is not eligible" in result.stderr
    assert not selection.output.exists()


def test_check_requires_isolation_and_absent_output(selection, monkeypatch):
    monkeypatch.setattr(ss, "sys", isolated_sys(False))
    assert ss.main(selection.argv + ["--check"]) == 2
    monkeypatch.setattr(ss, "sys", isolated_sys(True))
    selection.output.mkdir()
    assert ss.main(selection.argv + ["--check"]) == 2


def test_verified_runtime_requires_prefix_bootstrap_and_exact_versions(selection, tmp_path, monkeypatch):
    data = selection.data
    data["runtime_clearance"] = ss.CLEARANCE
    data["runtime_fields"]["python_executable"] = sys.executable
    bootstrap = tmp_path / "pyvenv.cfg"
    bootstrap.write_text("version_info = 3.12.13")
    data["runtime_fields"]["bootstrap_sources"] = [{"path": str(bootstrap), "sha256": ss.digest(bootstrap), "bytes": bootstrap.stat().st_size}]
    monkeypatch.setattr(ss, "sys", isolated_sys(True))
    monkeypatch.setattr(ss.platform, "python_version", lambda: "3.12.13")
    monkeypatch.setattr(ss.importlib.metadata, "version", ss.DIRECT_PACKAGES.__getitem__)
    assert ss.runtime_report(data)["ready"]
    data["runtime_fields"]["python_executable"] = str(Path(sys.executable).resolve()) + "-other-prefix"
    with pytest.raises(ValueError, match="venv-prefix"):
        ss.runtime_report(data)
    data["runtime_fields"]["python_executable"] = sys.executable
    bootstrap.write_text("changed")
    with pytest.raises(ValueError, match="differs"):
        ss.runtime_report(data)


def test_environment_keeps_home_and_drops_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/explicit/home")
    monkeypatch.setenv("CODEX_HOME", "/explicit/codex")
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setenv("QWEN_MM_CONFIG", "/home/untrusted-config")
    session = ss.prepare_session(tmp_path / "owned")
    env = ss.session_environment(session)
    assert env["HOME"] == "/explicit/home" and env["CODEX_HOME"] == "/explicit/codex"
    assert "OPENAI_API_KEY" not in env
    assert env["QWEN_MM_NATIVE_MODE"] == "1" and env["MPLBACKEND"] == "Agg"
    for key in ("TMPDIR", "MPLCONFIGDIR", "QWEN_MM_CONFIG_DIR", "QWEN_MM_CACHE"):
        assert Path(env[key]).is_dir() and Path(env[key]).is_relative_to(tmp_path / "owned")
    assert Path(env["QWEN_MM_CONFIG"]).read_text() == ""
    with pytest.raises(FileExistsError):
        ss.prepare_session(tmp_path / "owned")


def test_actual_footprint_retains_stdlib_bootstrap_and_rejects_extra_source(selection, monkeypatch):
    module_path = selection.root / sorted(ss.SOURCES)[0]
    bootstrap = selection.root.parent / "bootstrap.pth"
    bootstrap.write_text("# owned qualified bootstrap")
    selection.data["runtime_fields"]["bootstrap_sources"] = [{"path": str(bootstrap), "sha256": ss.digest(bootstrap), "bytes": bootstrap.stat().st_size}]
    monkeypatch.setitem(sys.modules, "spatial_test_selected", SimpleNamespace(__file__=str(module_path)))
    footprint = ss.loaded_footprint(selection.data, selection.root)
    actual = {r["path"]: r for r in footprint["actual_loaded_files"]}
    assert str(module_path) in actual and str(bootstrap) in actual
    assert str(Path(json.__file__).resolve()) in actual
    assert actual[str(module_path)]["sha256"] == ss.digest(module_path)
    other = selection.root / "tool_trace.py"
    other.write_text("unadmitted")
    monkeypatch.setitem(sys.modules, "spatial_test_extra", SimpleNamespace(__file__=str(other)))
    with pytest.raises(ValueError, match="footprint"):
        ss.loaded_footprint(selection.data, selection.root)
