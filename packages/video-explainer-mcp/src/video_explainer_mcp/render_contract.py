"""Read the selected external renderer entry, input and exact output contract."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .file_io import open_regular
from .planning_sources import read_object

PINNED_REVISION = "c033e28d6eccae43c1762f4653f9c320b16b050e"
MAPPED_SOURCE_SHA256 = {
    "src/cli/main.py": "03f5f70003f55cd490430c1a7469af5362e916292082371c2dbde8e2f06e4fe4",
    "src/project/__init__.py": "baed28685e748d7621653651feda171e10d33790645f676929f2cce142e43ea1",
    "src/pipeline/orchestrator.py": "902090d781dcbe1e430433bab7e301a980be15af09cda81989b0121c28b235fe",
    "src/animation/renderer.py": "e2c05a82322d6960242dc6453ec257f5be60e164a3692cfcb573dd5bf4fbd69f",
    "remotion/scripts/render.mjs": "c7a2e51b00575da0d1ddf95257bab6f3fabcf988a86d207a2b16e25812845df7",
}
RENDER_FLAGS = ["render PROJECT", "-r RESOLUTION", "--fast"]
AUTHORED_FILES = ("package.json", "src/index.ts", "src/Root.tsx", "src/Fixture.tsx",
                  "render_entry.mjs", "package-lock.json")


def source_contract(directory: Path) -> dict:
    """Identify reviewed mapped bytes without importing or invoking foreign code."""
    hashes = {}
    errors = []
    for name, expected in MAPPED_SOURCE_SHA256.items():
        try:
            with open_regular(directory / name) as (stream, info):
                if info.st_size > 8 * 1024 * 1024:
                    raise ValueError("External renderer source exceeds8MiB")
                body = stream.read(8 * 1024 * 1024 + 1)
                if len(body) > 8 * 1024 * 1024:
                    raise ValueError("External renderer source exceeds 8 MiB")
            hashes[name] = hashlib.sha256(body).hexdigest()
            if hashes[name] != expected:
                errors.append(f"Reviewed renderer source changed: {name}")
        except (OSError, ValueError) as exc:
            errors.append(f"Renderer source unavailable: {name}: {exc}")
    return {
        "mapped_source_verified": not errors,
        "revision": PINNED_REVISION,
        "file_sha256": hashes,
        "errors": errors,
        "public_render_flags": RENDER_FLAGS,
        "source_grant": "unresolved; no source is imported or redistributed",
        "runtime_and_asset_grants": "operator-owned; not certified by doctor",
        "foreign_runtime_executed": False,
    }


def project_contract(project: Path, resolution: str) -> dict:
    """Reject the pinned CLI's storyboard-path mismatch and bind its expected output."""
    config, _ = read_object(project / "config.json", project)
    paths = config.get("paths", {})
    if not isinstance(paths, dict):
        raise ValueError("Project paths must be a JSON object")
    storyboard = paths.get("storyboard", "storyboard")
    if storyboard != "storyboard/storyboard.json":
        raise ValueError(
            "Pinned public render requires paths.storyboard=storyboard/storyboard.json; "
            "its Node entry ignores configured alternatives"
        )
    read_object(project / storyboard, project)
    output = (
        paths.get("final_video", "final_video")
        if resolution == "1080p"
        else f"output/final-{resolution}.mp4"
    )
    if not isinstance(output, str) or Path(output).is_absolute():
        raise ValueError("Render output must be an explicit confined relative MP4 path")
    target = project / output
    if target.parent != project / "output" or target.suffix != ".mp4":
        raise ValueError("Render output must be a direct MP4 in the output directory; nested/traversal paths are unsupported")
    if target.is_symlink() or target.parent.is_symlink():
        raise ValueError("Render output or its directory cannot be a symlink")
    return {"storyboard_path": str(project / storyboard), "expected_output": str(target)}
