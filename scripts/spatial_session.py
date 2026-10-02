"""Serve original pinned Qwen spatial tools through an optional owned offline route.

The external Qwen source remains unmodified under its full Apache-2.0 grant.
Source admission is separate from dependency grants and geometry acceptance.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from spatial_inputs import Inputs, admit_file, digest  # noqa: E402
from spatial_dispatch import ProviderBarrier, configure_specs  # noqa: E402

REVISION = "07736672525443c7f8a3f6405eed37d2236f023f"
PACKAGE = "src/capabilities/video-spatio/qwen_mm_plugins_video_spatio"
TOOLS = frozenset("""
assess_coverage assess_reachable build_scene calibrate_scale camera_motion count_objects
match_entities mobile_manip motion object_world_motion orient_facing plan_exploration
render_scene_views scene_map select_keyframes triangulate verify_grounding view_reason visualize_bev
""".split())
TOOL_MODULES = (TOOLS - {"assess_coverage"}) | {"explore", "__init__", "_scene", "_vlm"}
SOURCES = frozenset(
    [f"{PACKAGE}/{name}.py" for name in (
        "__init__", "__main__", "camera_poses", "frame_image", "geometry", "prompts", "scene_types", "visual_feedback")]
    + [f"{PACKAGE}/tools/{name}.py" for name in TOOL_MODULES]
    + [f"{PACKAGE}/experts/{name}.py" for name in (
        "__init__", "base", "counting_expert", "entity_matcher", "grounding_verifier", "keyframe_selector",
        "mobile_expert", "motion_expert", "orientation_expert", "reconstruct", "scene_expert", "view_expert")]
    + ["src/mcp_framework.py"]
    + [f"src/shared/{name}.py" for name in (
        "__init__", "api_openai", "content", "dashscope_upload", "env", "image", "native_mode", "oss", "retry", "syscmd", "video")]
)
GRANTS = frozenset({"LICENSE"})
DIRECT_PACKAGES = {"mcp": "1.30.0", "pillow": "11.3.0", "openai": "1.109.1", "anyio": "4.15.1",
                   "pydantic": "2.13.5", "docstring-parser": "0.18.0",
                   "numpy": "2.4.4", "matplotlib": "3.10.9"}
CLEARANCE = "verified-selected-runtime-grants"


def admit_sources(root: Path, manifest: Path, sha256: str) -> dict:
    """Readmit the exact 54-source upper bound and Apache grant before foreign import."""
    if digest(manifest) != sha256:
        raise ValueError("Descriptor differs from the independently trusted SHA256")
    data = json.loads(manifest.read_text())
    if data["schema_version"] != 1 or data["source_revision"] != REVISION:
        raise ValueError("Descriptor source revision/schema is outside this selected route")
    for key, expected in (("execution_sources", SOURCES), ("license_sources", GRANTS)):
        rows = data[key]
        if len(rows) != len(expected) or {row["path"] for row in rows} != expected:
            raise ValueError(f"Incomplete or unexpected {key}")
        for row in rows:
            path = root / row["path"]
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("Selected source/grant escapes its admitted root")
            admit_file({**row, "path": str(path.absolute())})
    for directory in (f"{PACKAGE}/tools", f"{PACKAGE}/experts"):
        actual = {p.relative_to(root).as_posix() for p in (root / directory).iterdir()}
        if actual != {p for p in SOURCES if p.startswith(f"{directory}/")}:
            raise ValueError("Unadmitted entries present in a foreign discovery directory")
    if len(data["expected_tools"]) != 19 or set(data["expected_tools"]) != TOOLS:
        raise ValueError("Descriptor must preserve all 19 original spatial tool specifications")
    return data


def runtime_report(data: dict) -> dict:
    """Report blocked source-only readiness or read exact selected installed metadata."""
    if data.get("runtime_clearance") != CLEARANCE:
        return {"ready": False, "state": "source-only-runtime-blocked",
                "runtime_clearance": data.get("runtime_clearance"), "foreign_imports": 0,
                "hint": "Do not serve until the selected complete runtime grants are verified"}
    if data["selected_python"] != "3.12.13" or data["selected_direct_packages"] != DIRECT_PACKAGES:
        raise ValueError("Runtime differs from the explicitly selected external profile")
    selected = data["runtime_fields"]["python_executable"]
    if not selected or str(Path(sys.executable).absolute()) != selected:
        raise ValueError("Actual interpreter is not the selected venv-prefix executable")
    bootstrap = data["runtime_fields"]["bootstrap_sources"]
    if not bootstrap:
        raise ValueError("Selected runtime bootstrap bytes must be explicitly admitted")
    for row in bootstrap:
        admit_file(row)
    versions = {}
    for name in DIRECT_PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    ready = bool(sys.flags.isolated) and platform.python_version() == "3.12.13" and versions == DIRECT_PACKAGES
    return {"ready": ready, "state": "runtime-prerequisites" if ready else "runtime-prerequisites-unmet",
            "python": platform.python_version(), "executable": sys.executable,
            "isolated": bool(sys.flags.isolated), "packages": versions}


def prepare_session(output: Path) -> dict:
    """Create an exclusive cwd/config/cache/MPL/temp profile without changing home."""
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name in ("cwd", "config", "cache", "mpl", "tmp"):
        (output / name).mkdir(mode=0o700)
    (output / "empty-config").write_text("")
    return {"output": str(output)}


def session_environment(session: dict) -> dict:
    """Use a credential whitelist and native image mode without provider settings."""
    allowed = ("HOME", "CODEX_HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    output = Path(session["output"])
    env.update(PATH="/usr/bin:/bin", TMPDIR=str(output / "tmp"),
               QWEN_MM_CONFIG=str(output / "empty-config"), QWEN_MM_CONFIG_DIR=str(output / "config"),
               QWEN_MM_CACHE=str(output / "cache"), QWEN_MM_NATIVE_MODE="1",
               MPLCONFIGDIR=str(output / "mpl"), MPLBACKEND="Agg",
               QWEN_MM_AUTOLAUNCH="0", QWEN_MM_NO_AUTO_INSTALL="1")
    return env


def loaded_footprint(data: dict, root: Path) -> dict:
    """Retain actual loaded filenames and hashes including stdlib and bootstrap bytes."""
    rows = {}
    for name, module in tuple(sys.modules.items()):
        for kind, value in (("module", getattr(module, "__file__", None)),
                            ("cached_bytecode", getattr(module, "__cached__", None))):
            if value and Path(value).is_file():
                path = Path(value).resolve()
                if path.is_relative_to(root.resolve()) and path.relative_to(root.resolve()).as_posix() not in SOURCES:
                    raise ValueError("Actual foreign module footprint exceeds the admitted source upper bound")
                row = rows.setdefault(str(path), {"path": str(path), "sha256": digest(path),
                                                 "bytes": path.stat().st_size, "modules": [], "kind": kind})
                row["modules"].append(name)
    for row in data["runtime_fields"]["bootstrap_sources"]:
        admit_file(row)
        rows.setdefault(row["path"], {**row, "modules": [], "kind": "venv_bootstrap"})
    return {"python_executable": sys.executable, "python_prefix": sys.prefix,
            "selected_static_upper_bound": 54, "actual_loaded_files": list(rows.values())}


def serve(args, data: dict, inputs: Inputs) -> None:
    """Import only after verified runtime clearance and serve all original 19 specs."""
    if data.get("runtime_clearance") != CLEARANCE:
        raise ValueError("Runtime grants are blocked; no foreign import or component execution authorized")
    if not runtime_report(data)["ready"]:
        raise ValueError("Selected external runtime prerequisites failed")
    session = prepare_session(args.output.absolute())
    output = Path(session["output"])
    env = session_environment(session)
    os.environ.clear()
    os.environ.update(env)
    os.chdir(output / "cwd")
    tempfile.tempdir = None
    root = args.source_root.absolute()
    def read_sources():
        return admit_sources(root, args.manifest, args.manifest_sha256)
    read_sources()
    sys.path[:0] = [str(root / "src"), str(root / "src/capabilities/video-spatio")]
    package = importlib.import_module("qwen_mm_plugins_video_spatio")
    framework = importlib.import_module("mcp_framework")
    if len(package.SPECS) != 19 or {spec.name for spec in package.SPECS} != TOOLS:
        raise ValueError("Actual discovery differs from the 19 admitted original tools")
    barrier = ProviderBarrier()
    barrier.install(importlib.import_module("qwen_mm_plugins_video_spatio.tools._vlm").VLMShim)
    read_sources()
    (output / "loaded-startup.json").write_text(json.dumps(loaded_footprint(data, root), indent=2))

    def evidence(name, result):
        value = {"tool": name, "response": result, "loaded": loaded_footprint(data, root)}
        with (output / "calls.jsonl").open("a") as stream:
            stream.write(json.dumps(value, allow_nan=False) + "\n")

    configure_specs(package.SPECS, inputs, barrier, importlib.import_module, read_sources, evidence)
    framework.serve("qwen-mm-plugins-video-spatio", package.__version__, package.SPECS)


def main(argv=None) -> int:
    """Perform read-only source/input checks or explicitly serve a qualified optional session."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-root", "manifest", "inputs", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("manifest-sha256", "inputs-sha256"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not sys.flags.isolated:
            raise ValueError("Select the explicit external interpreter with -I -B")
        data = admit_sources(args.source_root.absolute(), args.manifest, args.manifest_sha256)
        inputs = Inputs(args.inputs.absolute(), args.inputs_sha256)
        if args.output.exists():
            raise ValueError("Owned output must be absent")
        report = {"sources_admitted": True, "source_files": 54, "source_grants": 1,
                  "inputs_admitted": True, "frames": len(inputs.frames), **runtime_report(data)}
        if args.check:
            print(json.dumps(report))
            return 0 if report["ready"] else 2
        if not report["ready"]:
            raise ValueError(f"Runtime is not eligible: {report}")
        serve(args, data, inputs)
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(f"Spatial session refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
