"""Source-only admission and original discovery stubs; foreign activation stays unrun."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import core_inputs
import core_session as session


def source_contract(tmp_path, monkeypatch):
    """Create the exact selected tree with inert first-party source bytes."""
    root = tmp_path / "source"
    rows = []
    for name in sorted(session.SOURCES | {"LICENSE", "pyproject.toml"}):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        body = b"# handler contract stub; never imported\n" if name.endswith(".py") else b"first-party admission fixture\n"
        path.write_bytes(body)
        rows.append({"path": name, "bytes": len(body), "sha256": core_inputs.sha256(body)})
    monkeypatch.setattr(session, "GRANT_SHA256", rows[[r["path"] for r in rows].index("LICENSE")]["sha256"])
    data = {"schema_version": 1, "source_revision": session.REVISION,
            "execution_sources": [r for r in rows if r["path"].endswith(".py")],
            "license_sources": [r for r in rows if r["path"] == "LICENSE"],
            "declaration_sources": [r for r in rows if r["path"] == "pyproject.toml"],
            "expected_tools": [{"name": n, "input_schema": {"type": "object"}} for n in sorted(session.TOOLS)],
            "runtime_clearance": "source-only-runtime-unqualified", "format_clearance": {"pdf": {"state": "unqualified"}}}
    binding = core_inputs.write_json(tmp_path / "descriptor.json", data)
    return root, data, binding


def test_exact_source_population_read_only_and_no_foreign_import(tmp_path, monkeypatch):
    root, data, binding = source_contract(tmp_path, monkeypatch)
    monkeypatch.setattr(session.importlib, "import_module", lambda *_: pytest.fail("foreign import"))
    assert session.admit_sources(root, binding["path"], binding["sha256"]) == data
    monkeypatch.setattr(session, "runtime_payload", lambda *_: pytest.fail("blocked runtime read"))
    assert session.runtime_report(data)["foreign_imports"] == 0
    with pytest.raises(ValueError, match="blocked"):
        session.load_core(data, root, tmp_path)


@pytest.mark.parametrize("change", ["source", "grant", "declaration", "extra", "symlink", "bytecode", "descriptor", "src-shadow"])
def test_source_grant_extraneous_and_trusted_descriptor_refusals(tmp_path, monkeypatch, change):
    root, _, binding = source_contract(tmp_path, monkeypatch)
    if change == "descriptor":
        Path(binding["path"]).write_bytes(b"{}")
    elif change in {"source", "grant", "declaration"}:
        selected = next(iter(session.SOURCES)) if change == "source" else "LICENSE" if change == "grant" else "pyproject.toml"
        path = root / selected
        path.write_bytes(path.read_bytes() + b"altered")
    else:
        path = root / ("src/unselected.py" if change == "src-shadow" else session.PACKAGE + ("/__pycache__/cached.pyc" if change == "bytecode" else "/foreign.py"))
        path.parent.mkdir(parents=True, exist_ok=True)
        if change == "symlink":
            path.symlink_to(root / "LICENSE")
        else:
            path.write_bytes(b"not selected")
    with pytest.raises(ValueError):
        session.admit_sources(root, binding["path"], binding["sha256"])


def test_check_does_not_create_output_or_query_runtime_metadata(tmp_path, monkeypatch, capsys):
    root, _, binding = source_contract(tmp_path, monkeypatch)
    path = tmp_path / "operator.py"
    path.write_bytes(b"data\n")
    inputs = core_inputs.write_json(tmp_path / "inputs.json", {"schema_version": 1, "files": [{"path": str(path), "bytes": 5, "sha256": core_inputs.sha256(b"data\n")}]})
    monkeypatch.setattr(session, "isolated_mode", lambda: True)
    monkeypatch.setattr(session.importlib.metadata, "version", lambda *_: pytest.fail("runtime query"))
    command = ["--source-root", str(root), "--manifest", binding["path"], "--manifest-sha256", binding["sha256"], "--inputs", inputs["path"], "--inputs-sha256", inputs["sha256"], "--output", str(tmp_path / "absent"), "--check"]
    assert session.main(command) == 2
    assert json.loads(capsys.readouterr().out)["state"] == "source-only-runtime-blocked"
    assert not (tmp_path / "absent").exists()
    assert session.main(command[:-1]) == 2
    assert not (tmp_path / "absent").exists()


def test_home_preserved_credentials_not_inherited_and_exclusive_namespace(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/operator/home")
    monkeypatch.setenv("CODEX_HOME", "/operator/codex")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("PYTHONPATH", "/unowned")
    output = session.prepare_session(tmp_path / "session")
    env = session.session_environment(output)
    assert env["HOME"] == "/operator/home" and env["CODEX_HOME"] == "/operator/codex"
    assert "GEMINI_API_KEY" not in env and "PYTHONPATH" not in env
    assert env["QWEN_MM_NATIVE_MODE"] == "1"
    assert (output / "config/config").read_bytes() == b""
    with pytest.raises(FileExistsError):
        session.prepare_session(output)


@pytest.mark.parametrize("cache", [None, "relative", "existing", "absent"])
def test_isolated_flags_include_unadmitted_bytecode_refusal(tmp_path, monkeypatch, cache):
    path = tmp_path / "cache"
    if cache == "existing":
        path.mkdir()
    value = None if cache is None else "relative" if cache == "relative" else str(path)
    monkeypatch.setattr(session, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=1, dont_write_bytecode=1), pycache_prefix=value))
    assert session.isolated_mode() == (cache == "absent")


def test_runtime_readback_never_drops_large_selected_manifest(tmp_path):
    files = []
    site = tmp_path / "lib/python3.12/site-packages"
    site.mkdir(parents=True)
    for n in range(2157):
        path = site / f"selected-{n}"
        path.write_bytes(b"s")
        files.append({"path": str(path), "bytes": 1, "sha256": core_inputs.sha256(b"s")})
    packages = {**session.PACKAGES, **{f"extra{n}": "1.0" for n in range(30)}}
    runtime = core_inputs.write_json(tmp_path / "runtime.json", {"schema_version": 1, "files": files, "packages": packages}, 1048576)
    grant_rows = []
    for n in range(40):
        path = tmp_path / f"grant-{n}"
        path.write_bytes(b"g")
        grant_rows.append({"path": str(path), "bytes": 1, "sha256": core_inputs.sha256(b"g")})
    grants = core_inputs.write_json(tmp_path / "grants.json", {"rows": grant_rows})
    data = {"runtime_fields": {"python_prefix": str(tmp_path), "runtime_manifest": runtime, "runtime_grants": grants, "python_binary": files[0], "bootstrap_sources": files[1:4]}}
    assert len(session.runtime_payload(data)["files"]) == 2157
    Path(files[-1]["path"]).write_bytes(b"x")
    with pytest.raises(ValueError):
        session.runtime_payload(data)
    Path(files[-1]["path"]).write_bytes(b"s")
    Path(grant_rows[-1]["path"]).write_bytes(b"x")
    with pytest.raises(ValueError):
        session.runtime_payload(data)
    Path(grant_rows[-1]["path"]).write_bytes(b"g")
    (site / "unselected-startup.pth").write_bytes(b"import unselected\n")
    with pytest.raises(ValueError, match="discovery"):
        session.runtime_payload(data)


@pytest.mark.parametrize("layout", ["checkout", "wheel"])
def test_concrete_shared_eof_helper_locations(tmp_path, monkeypatch, layout):
    if layout == "checkout":
        script = tmp_path / "scripts/core_session.py"
        helper = script.parent / "blender_stdio.py"
    else:
        script = tmp_path / "freecad/scripts/core_session.py"
        helper = tmp_path / "blender/scripts/blender_stdio.py"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text("# location contract only\n")
    def cleanup():
        pass
    monkeypatch.setattr(session, "__file__", str(script))
    monkeypatch.setitem(sys.modules, "blender_stdio", SimpleNamespace(eof_transport=lambda value: ("transport", value)))
    assert session.helper_transport(cleanup) == ("transport", cleanup)


def test_startup_exports_actual_specs_annotations_and_registry_without_renderer_calls(monkeypatch):
    renderer = SimpleNamespace(SUPPORTED_EXTENSIONS={".py", ".R"}, _REGISTRY={".py": ("code", "render")})
    monkeypatch.setattr(session.importlib, "import_module", lambda name: renderer)
    spec = SimpleNamespace(meta={"name": "visualize", "description": "actual", "inputSchema": {"type": "object"}}, annotations=None, output_schema=None)
    result = session.startup_inventory(SimpleNamespace(SPECS=[spec]))
    assert result["registry"][".py"] == ["code", "render"]
    assert result["specs"][0]["description"] == "actual"
    assert "annotations" in result["specs"][0] and "outputSchema" in result["specs"][0]
