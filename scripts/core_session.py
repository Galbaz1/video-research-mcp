"""Optional original pinned core session; blocked checks never import foreign packages."""

import argparse
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import signal
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core_inputs import Inputs, canonical, read_body, sha256, trusted_json, verify, write_json  # noqa: E402
from core_dispatch import Barrier, Dispatch, execute_handler  # noqa: E402

REVISION = "07736672525443c7f8a3f6405eed37d2236f023f"
PACKAGE = "src/capabilities/core/qwen_mm_plugins_core"
TOOLS = frozenset({"read_image", "read_video", "media_info", "visualize", "crop", "draw_bbox", "save_view"})
SOURCES = frozenset({
    'src/capabilities/core/qwen_mm_plugins_core/__init__.py',
    'src/capabilities/core/qwen_mm_plugins_core/__main__.py',
    'src/capabilities/core/qwen_mm_plugins_core/producers/__init__.py',
    'src/capabilities/core/qwen_mm_plugins_core/producers/crop.py',
    'src/capabilities/core/qwen_mm_plugins_core/producers/draw_bbox.py',
    'src/capabilities/core/qwen_mm_plugins_core/producers/save_view.py',
    'src/capabilities/core/qwen_mm_plugins_core/readers/__init__.py',
    'src/capabilities/core/qwen_mm_plugins_core/readers/image.py',
    'src/capabilities/core/qwen_mm_plugins_core/readers/media_info.py',
    'src/capabilities/core/qwen_mm_plugins_core/readers/video.py',
    'src/capabilities/core/qwen_mm_plugins_core/renderers/__init__.py',
    'src/capabilities/core/qwen_mm_plugins_core/renderers/_blender_render.py',
    'src/capabilities/core/qwen_mm_plugins_core/renderers/_pyrender_worker.py',
    'src/capabilities/core/qwen_mm_plugins_core/renderers/code.py',
    'src/capabilities/core/qwen_mm_plugins_core/renderers/data.py',
    'src/capabilities/core/qwen_mm_plugins_core/renderers/drawio.py',
    'src/capabilities/core/qwen_mm_plugins_core/renderers/geo.py',
    'src/capabilities/core/qwen_mm_plugins_core/renderers/latex.py',
    'src/capabilities/core/qwen_mm_plugins_core/renderers/model3d.py',
    'src/capabilities/core/qwen_mm_plugins_core/renderers/nifti.py',
    'src/capabilities/core/qwen_mm_plugins_core/renderers/notebook.py',
    'src/capabilities/core/qwen_mm_plugins_core/renderers/office.py',
    'src/capabilities/core/qwen_mm_plugins_core/renderers/pdf.py',
    'src/capabilities/core/qwen_mm_plugins_core/renderers/subtitle.py',
    'src/capabilities/core/qwen_mm_plugins_core/renderers/svg.py',
    'src/capabilities/core/qwen_mm_plugins_core/renderers/web.py',
    'src/capabilities/core/qwen_mm_plugins_core/stdio_streaming.py',
    'src/capabilities/core/qwen_mm_plugins_core/visualizers/__init__.py',
    'src/capabilities/core/qwen_mm_plugins_core/visualizers/visualize.py',
    'src/mcp_framework.py',
    'src/shared/__init__.py',
    'src/shared/cache.py',
    'src/shared/content.py',
    'src/shared/env.py',
    'src/shared/image.py',
    'src/shared/isolated_worker.py',
    'src/shared/native_mode.py',
    'src/shared/paths.py',
    'src/shared/syscmd.py',
    'src/shared/video.py',
})
PACKAGES = {"mcp": "1.30.0", "pillow": "11.3.0", "openai": "1.109.1", "anyio": "4.15.1",
            "pydantic": "2.13.5", "docstring-parser": "0.18.0"}
CLEARANCE = "verified-selected-runtime-grants"
GRANT_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"


def isolated_mode():
    """Keep isolated/bytecode flags testable without replacing global interpreter flags."""
    return bool(sys.flags.isolated and sys.flags.dont_write_bytecode and sys.pycache_prefix
                and Path(sys.pycache_prefix).is_absolute() and not Path(sys.pycache_prefix).exists())


def admit_sources(root, manifest, expected):
    """Read the exact40 Python upper bound, original grant and declaration before import."""
    root = canonical(str(root))
    data = trusted_json(manifest, expected)
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1 or data["source_revision"] != REVISION:
        raise ValueError("Core descriptor revision/schema is outside the pinned integration")
    for key, required in (("execution_sources", SOURCES), ("license_sources", {"LICENSE"}), ("declaration_sources", {"pyproject.toml"})):
        rows = data[key]
        if len(rows) != len(required) or {r["path"] for r in rows} != required:
            raise ValueError("Core source/grant/declaration population is incomplete or unexpected")
        for row in rows:
            verify({**row, "path": str(root / row["path"])})
    if data["license_sources"][0]["sha256"] != GRANT_SHA256:
        raise ValueError("Core requires the complete pinned Apache grant")
    actual = {p.relative_to(root).as_posix() for p in (root / "src").rglob("*") if p.is_file() or p.is_symlink()}
    if actual != SOURCES:
        raise ValueError("Unadmitted source/discovery entries are present")
    if len(data["expected_tools"]) != 7 or {r["name"] for r in data["expected_tools"]} != TOOLS:
        raise ValueError("All seven exact original tool contracts must remain discoverable")
    return data


def runtime_payload(data):
    """Rejoin the compact selected file and grant manifests, without importing their code."""
    fields = data["runtime_fields"]
    payload = trusted_json(fields["runtime_manifest"]["path"], fields["runtime_manifest"]["sha256"], 1048576)
    if len(read_body(fields["runtime_manifest"]["path"], 1048576)) != fields["runtime_manifest"]["bytes"]:
        raise ValueError("Selected runtime manifest byte count changed")
    if payload["schema_version"] != 1 or len(payload["files"]) != 2157 or len({r["path"] for r in payload["files"]}) != 2157 or len(payload["packages"]) != 36:
        raise ValueError("Selected base runtime must retain all2157 files and36 packages")
    grants = trusted_json(fields["runtime_grants"]["path"], fields["runtime_grants"]["sha256"], 1048576)
    if len(grants["rows"]) != 40 or len({row["path"] for row in grants["rows"]}) != 40:
        raise ValueError("Selected runtime requires the exact40 qualified grant bodies")
    if len(read_body(fields["runtime_grants"]["path"], 1048576)) != fields["runtime_grants"]["bytes"]:
        raise ValueError("Selected runtime grant manifest byte count changed")
    for row in [fields["python_binary"], *fields["bootstrap_sources"], *payload["files"], *grants["rows"]]:
        verify(row, 67108864)
    if len(fields["bootstrap_sources"]) != 3:
        raise ValueError("Selected runtime bootstrap/grant commitments are incomplete")
    site = canonical(fields["python_prefix"]) / "lib/python3.12/site-packages"
    actual = {str(p) for p in site.rglob("*") if (p.is_file() or p.is_symlink()) and not (p.suffix == ".pyc" and "__pycache__" in p.parts)}
    selected = {r["path"] for r in payload["files"] + fields["bootstrap_sources"] if Path(r["path"]).is_relative_to(site)}
    if actual != selected:
        raise ValueError("Selected installed-source discovery contains unadmitted entries")
    return payload


def runtime_report(data):
    """Keep source eligibility, selected metadata and actual format readiness distinct."""
    formats = data["format_clearance"]
    if data.get("runtime_clearance") != CLEARANCE:
        return {"ready": False, "state": "source-only-runtime-blocked", "foreign_imports": 0,
                "runtime_clearance": data.get("runtime_clearance"), "formats": formats}
    fields, payload = data["runtime_fields"], runtime_payload(data)
    if not isolated_mode() or platform.python_version() != "3.12.13" or str(Path(sys.executable).absolute()) != fields["python_executable"] or sys.prefix != fields["python_prefix"]:
        raise ValueError("Use exactly the selected interpreter prefix with -I -B")
    actual = {name: importlib.metadata.version(name) for name in payload["packages"]}
    if actual != payload["packages"] or any(actual.get(k) != v for k, v in PACKAGES.items()):
        raise ValueError("Selected dependency metadata changed")
    return {"ready": True, "state": "base-runtime-admitted-formats-separate", "packages": actual,
            "executable": sys.executable, "formats": formats, "actual_preview_acceptance": "unverified"}


def session_environment(output):
    """Preserve home identities while excluding credentials and provider/autoinstall settings."""
    env = {k: os.environ[k] for k in ("HOME", "CODEX_HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE") if k in os.environ}
    env.update(PATH="/usr/bin:/bin", TMPDIR=str(output / "tmp"), QWEN_MM_CONFIG=str(output / "config/config"),
               QWEN_MM_CONFIG_DIR=str(output / "config"), QWEN_MM_CACHE=str(output / "cache"),
               QWEN_MM_NATIVE_MODE="1", QWEN_MM_AUTOLAUNCH="0", QWEN_MM_NO_AUTO_INSTALL="1")
    return env


def prepare_session(output):
    """Own an absent namespace; never attach to or resume prior workers/artifacts."""
    output = canonical(str(output))
    output.mkdir(mode=0o700, exist_ok=False)
    for name in ("cwd", "config", "cache", "tmp", "calls"):
        (output / name).mkdir(mode=0o700)
    (output / "config/config").write_bytes(b"")
    return output


def loaded_footprint(data, root):
    """Bind actual loaded source/runtime/stdlib bytes and refuse a larger foreign closure."""
    payload = runtime_payload(data)
    admitted = {r["path"] for r in payload["files"] + data["runtime_fields"]["bootstrap_sources"]}
    files = {}
    for name, module in tuple(sys.modules.items()):
        for kind, value in (("module", getattr(module, "__file__", None)), ("bytecode", getattr(module, "__cached__", None))):
            if not value or not Path(value).is_file():
                continue
            path = Path(value).resolve()
            if path.is_relative_to(root) and path.relative_to(root).as_posix() not in SOURCES:
                raise ValueError("Loaded original-source footprint exceeds40 selected bodies")
            if path.is_relative_to(Path(sys.prefix)) and str(path) not in admitted and not path.is_relative_to(Path(__file__).resolve().parent):
                raise ValueError("Loaded dependency/bytecode is outside the selected runtime files")
            body = read_body(path, 67108864)
            row = files.setdefault(str(path), {"path": str(path), "bytes": len(body), "sha256": sha256(body), "kind": kind, "modules": []})
            row["modules"].append(name)
    return {"pid": os.getpid(), "python_executable": sys.executable, "python_prefix": sys.prefix,
            "static_original_source_upper_bound": 40, "files": list(files.values()), "bootstrap": data["runtime_fields"]["bootstrap_sources"]}


def load_core(data, root, output):
    """Import the unchanged original package only inside an explicitly admitted session."""
    if not runtime_report(data)["ready"]:
        raise ValueError("Core runtime is blocked before foreign import")
    env = session_environment(output)
    os.environ.clear()
    os.environ.update(env)
    os.chdir(output / "cwd")
    tempfile.tempdir = None
    barrier = Barrier(output)
    sys.addaudithook(barrier.audit)
    sys.path[:0] = [str(root / "src"), str(root / "src/capabilities/core")]
    package = importlib.import_module("qwen_mm_plugins_core")
    framework = importlib.import_module("mcp_framework")
    expected = {row["name"]: row["input_schema"] for row in data["expected_tools"]}
    if len(package.SPECS) != 7 or {s.name: s.input_schema for s in package.SPECS} != expected:
        raise ValueError("Actual original discovery/schema differs from all seven contracts")
    renderer = importlib.import_module("qwen_mm_plugins_core.renderers")
    if sorted(renderer.SUPPORTED_EXTENSIONS) != data["supported_extensions"]:
        raise ValueError("Actual75-extension inventory differs from the original registry")
    if {key: list(value) for key, value in renderer._REGISTRY.items()} != data["registry"]:
        raise ValueError("Actual62-entry dispatch registry differs from the original source")
    barrier.check()
    return package, framework, barrier


def startup_inventory(package):
    """Retain actual normalized discovery and lazy registry exports, without heavy dispatch."""
    renderer = importlib.import_module("qwen_mm_plugins_core.renderers")
    return {"supported_extensions": sorted(renderer.SUPPORTED_EXTENSIONS),
            "registry": {k: list(v) for k, v in renderer._REGISTRY.items()},
            "specs": [{**s.meta, "annotations": getattr(s, "annotations", None),
                       "outputSchema": getattr(s, "output_schema", None)} for s in package.SPECS]}


def helper_transport(cleanup):
    """Reuse accepted EOF-before-shielded-worker-join in checkout and current wheel layout."""
    helper = Path(__file__).resolve().parent
    if not (helper / "blender_stdio.py").is_file():
        helper = Path(__file__).resolve().parents[2] / "blender/scripts"
    sys.path.insert(0, str(helper))
    from blender_stdio import eof_transport
    return eof_transport(cleanup)


def serve(args, data, inputs):
    """Serve original specs while one owned worker group handles each admitted call."""
    if not runtime_report(data)["ready"]:
        raise ValueError("Core runtime grants are blocked before foreign import")
    output = prepare_session(args.output)
    package, framework, barrier = load_core(data, args.source_root, output)
    def recheck():
        admit_sources(args.source_root, args.manifest, args.manifest_sha256)
        inputs.readback()
        runtime_report(data)
    dispatch = Dispatch(args, data, inputs, output, recheck, barrier)
    startup = {"loaded": loaded_footprint(data, args.source_root), "original_discovery": startup_inventory(package)}
    recheck()
    write_json(output / "loaded-startup.json", startup, 4194304)
    for spec in package.SPECS:
        spec.handle = dispatch.handler(spec.name)
    previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    def stop(signum, _):
        dispatch.close()
        raise KeyboardInterrupt
    for s in previous:
        signal.signal(s, stop)
    try:
        framework.serve("qwen-mm-plugins-core", package.__version__, package.SPECS, transport=helper_transport(dispatch.close))
    finally:
        dispatch.close()
        write_json(output / "session-terminal.json", {"state": "closed", "owned_workers_reaped": True})
        for s, handler in previous.items():
            signal.signal(s, handler)


def main(argv=None):
    """Read-only source check or explicit optional stdio serve; no upstream setup commands."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-root", "manifest", "inputs", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("manifest-sha256", "inputs-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--worker-job", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-sha256", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if not isolated_mode():
            raise ValueError("Select the exact interpreter with -I -B -X pycache_prefix=ABSENT_PRIVATE_PATH")
        args.source_root, args.output = canonical(str(args.source_root)), canonical(str(args.output))
        data = admit_sources(args.source_root, args.manifest, args.manifest_sha256)
        inputs = Inputs(args.inputs, args.inputs_sha256)
        if args.worker_job:
            return execute_handler(args, data, inputs, load_core, loaded_footprint)
        if args.output.exists():
            raise ValueError("Owned output must be absent; prior sessions are not resumed")
        report = {"source_admitted": True, "source_files": 40, "original_tools": 7, "declared_extensions": 75,
                  "inputs_admitted": len(inputs.files), **runtime_report(data)}
        if args.check:
            print(json.dumps(report, allow_nan=False))
            return 0 if report["ready"] else 2
        if not report["ready"]:
            raise ValueError("Core runtime is source-only blocked; no foreign import authorized")
        serve(args, data, inputs)
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(f"Core session refused: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
