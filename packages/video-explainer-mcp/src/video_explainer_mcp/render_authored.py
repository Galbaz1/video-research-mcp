"""Frozen, independently authored single-card renderer admission and qualification."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
from pathlib import Path

from .file_io import open_regular
from .media_process import run_media_process
from .planning_sources import canonical, read_object
from .render_artifacts import file_revision, verify_output
from .render_contract import AUTHORED_FILES
from .render_validation import codec_executables

COMPOSITION = {"id": "Fixture", "fps": 30, "width": 1280, "height": 720,
               "durationInFrames": 30}
PACKAGES = {"remotion": "4.0.532", "@remotion/renderer": "4.0.532",
            "@remotion/bundler": "4.0.532", "@remotion/compositor-darwin-arm64": "4.0.532",
            "react": "19.0.0", "react-dom": "19.0.0"}
FIXTURE_FILES = ("config.json", "storyboard/storyboard.json", "assets/fixture.wav")


def tree_revision(directory: Path) -> str:
    """Hash all installed regular bytes and confined symlink targets without import."""
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Renderer runtime directory must be a regular directory")
    files = {}
    for path in sorted(directory.rglob("*")):
        if len(files) >= 50000:
            raise ValueError("Renderer runtime exceeds 50000 files")
        name = path.relative_to(directory).as_posix()
        if path.is_symlink():
            path.resolve(strict=True).relative_to(directory.resolve())
            files[name] = {"symlink": os.readlink(path)}
        elif path.is_file():
            files[name] = file_revision(path, 512 * 1024 * 1024)
        elif not path.is_dir():
            raise ValueError("Renderer runtime contains a nonregular entry")
    return hashlib.sha256(canonical(files).encode()).hexdigest()


def _executable(value: dict) -> dict:
    """Require an absolute executable whose observed bytes match the external pin."""
    path = Path(value["path"])
    if not path.is_absolute() or not os.access(path, os.X_OK):
        raise ValueError("Renderer executable must be absolute and executable")
    revision = file_revision(path, 512 * 1024 * 1024)
    if revision["sha256"] != value["sha256"]:
        raise ValueError("Renderer executable hash changed")
    return {"path": str(path), **revision}


def authored_binding(cfg) -> dict:
    """Check the externally hashed root freeze before any selected runtime executes."""
    entry, spec_path = Path(cfg.renderer_entry), Path(cfg.renderer_spec)
    if not entry.is_absolute() or entry.name != "render_entry.mjs" or entry.is_symlink():
        raise ValueError("Authored entry must be an absolute regular render_entry.mjs")
    entry = entry.resolve(strict=True)
    if not spec_path.is_absolute() or spec_path.is_symlink():
        raise ValueError("Authored renderer requires an absolute regular frozen spec")
    if not re.fullmatch(r"[0-9a-f]{64}", cfg.renderer_spec_sha256):
        raise ValueError("Authored renderer requires an external spec SHA256")
    spec, sha = read_object(spec_path, spec_path.parent)
    if sha != cfg.renderer_spec_sha256:
        raise ValueError("Authored renderer spec hash changed")
    if spec.get("schema") != "vrm-authored-renderer/r1" or spec.get("composition") != COMPOSITION:
        raise ValueError("Unsupported authored renderer freeze/composition")
    if set(spec["entry_sha256"]) != set(AUTHORED_FILES):
        raise ValueError("Authored renderer freeze must bind all six entry files")
    revisions = {name: file_revision(entry.parent / name, 1024 * 1024)
                 for name in AUTHORED_FILES}
    if any(revisions[name]["sha256"] != sha for name, sha in spec["entry_sha256"].items()):
        raise ValueError("Authored renderer source hash changed")
    if spec.get("package_versions") != PACKAGES:
        raise ValueError("Unsupported authored renderer package versions")
    modules = entry.parent / "node_modules"
    for name, version in PACKAGES.items():
        package, _ = read_object(modules / name / "package.json", entry.parent)
        if package.get("name") != name or package.get("version") != version:
            raise ValueError(f"Authored renderer package changed: {name}")
    runtime_sha = tree_revision(modules)
    if runtime_sha != spec["node_modules_sha256"]:
        raise ValueError("Authored renderer installed bytes changed")
    if set(spec["fixture_sha256"]) != set(FIXTURE_FILES):
        raise ValueError("Authored renderer freeze must bind all three fixture inputs")
    browser = _executable(spec["browser"])
    browser_dir = Path(spec["browser"]["directory"])
    if not browser_dir.is_absolute() or not Path(browser["path"]).is_relative_to(browser_dir):
        raise ValueError("Browser resources require an absolute containing directory")
    browser_sha = tree_revision(browser_dir)
    if browser_sha != spec["browser"]["tree_sha256"]:
        raise ValueError("Authored browser resources changed")
    browser.update(directory=str(browser_dir), tree_sha256=browser_sha)
    return {"entry": str(entry), "spec": str(spec_path), "spec_sha256": sha,
            "entry_revision": revisions, "node_modules_sha256": runtime_sha,
            "node": _executable(spec["node"]), "browser": browser,
            "fixture_sha256": spec["fixture_sha256"]}


def authored_project(project: Path, resolution: str) -> dict:
    """Refuse every storyboard except one second of the explicit PCM solid card."""
    if resolution != "720p":
        raise ValueError("Authored fixture supports only 720p")
    config, _ = read_object(project / "config.json", project)
    paths = config.get("paths", {})
    if not isinstance(paths, dict) or paths.get("storyboard", "storyboard/storyboard.json") != "storyboard/storyboard.json":
        raise ValueError("Unsupported authored storyboard route")
    output = project / "output/final-720p.mp4"
    if output.parent.is_symlink():
        raise ValueError("Authored output directory cannot be a symlink")
    contract = {"storyboard_path": str(project / "storyboard/storyboard.json"), "expected_output": str(output)}
    board, _ = read_object(project / "storyboard/storyboard.json", project)
    scenes = board.get("scenes")
    if set(board) != {"scenes"} or not isinstance(scenes, list) or len(scenes) != 1:
        raise ValueError("Unsupported storyboard: authored fixture requires exactly one scene")
    scene = scenes[0]
    keys = {"id", "title", "audio_duration_seconds", "scene_buffer_seconds",
            "visual_padding_seconds", "audio_file", "card_color"}
    if not isinstance(scene, dict) or set(scene) != keys:
        raise ValueError("Unsupported storyboard fields for authored fixture")
    if (scene["id"] != "fixture" or not isinstance(scene["title"], str)
            or scene["audio_duration_seconds"] != 1.0
            or isinstance(scene["audio_duration_seconds"], bool)
            or scene["scene_buffer_seconds"] != 0 or scene["visual_padding_seconds"] != 0
            or isinstance(scene["scene_buffer_seconds"], bool) or isinstance(scene["visual_padding_seconds"], bool)
            or scene["audio_file"] != "fixture.wav"):
        raise ValueError("Unsupported authored fixture duration, padding or audio path")
    if not isinstance(scene["card_color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", scene["card_color"]):
        raise ValueError("Authored card color must be a six-digit hex color")
    audio = project / "assets/fixture.wav"
    with open_regular(audio) as (stream, info):
        if info.st_size != 96044:
            raise ValueError("Fixture WAV must contain exactly 48000 PCM16 mono samples")
        header = stream.read(44)
    expected = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 96036, b"WAVE", b"fmt ",
                           16, 1, 1, 48000, 96000, 2, 16, b"data", 96000)
    if header != expected:
        raise ValueError("Fixture WAV requires canonical 48kHz mono PCM16 RIFF")
    if sorted(path.name for path in (project / "assets").iterdir()) != ["fixture.wav"]:
        raise ValueError("Unsupported extra fixture assets")
    if output.exists() or output.is_symlink() or Path(str(output) + ".receipt.json").exists() or Path(str(output) + ".receipt.json").is_symlink():
        raise ValueError("Authored render requires a fresh output; retained files are refused")
    return {**contract, "input_props": {"color": scene["card_color"], "audio_file": "fixture.wav",
                                       "audio_duration_seconds": 1.0}}


def bind_fixture(project: Path, binding: dict) -> None:
    """Reject any input bytes outside the root-frozen fixture."""
    for name, sha in binding["fixture_sha256"].items():
        if file_revision(project / name, 1024 * 1024)["sha256"] != sha:
            raise ValueError(f"Root-frozen fixture changed: {name}")


def _receipt(artifact: dict, request: dict) -> dict:
    """Join renderer receipt identity, frozen inputs and exact current output bytes."""
    path = Path(artifact["path"] + ".receipt.json")
    receipt, sha = read_object(path, path.parent)
    binding = request["renderer"]
    if (receipt.get("schema") != "vrm-authored-render-receipt/r1"
            or receipt.get("execution_token") != request["execution_token"]
            or receipt.get("spec_sha256") != binding["spec_sha256"]
            or receipt.get("fixture_sha256") != binding["fixture_sha256"]
            or receipt.get("composition") != COMPOSITION
            or receipt.get("browser_sha256") != binding["browser"]["sha256"]
            or receipt.get("package_versions") != PACKAGES
            or receipt.get("output") != {k: artifact[k] for k in ("path", "sha256", "size_bytes")}):
        raise ValueError("Authored receipt differs from persisted request/output identity")
    return {"path": str(path), "sha256": sha, "execution_token": request["execution_token"]}


async def qualify_authored(artifact: dict, qualification: dict, request: dict) -> dict:
    """Require 30 frames and stereo AAC; Remotion up-mixes the mono input with -ac 2."""
    if artifact["size_bytes"] > 16 * 1024 * 1024:
        raise ValueError("Authored output exceeds 16 MiB")
    duration = qualification["media"]["duration_seconds"]
    if not math.isfinite(duration) or abs(duration - 1.0) > 1 / 30:
        raise ValueError("Authored output duration differs from one second")
    receipt = _receipt(artifact, request)
    executables = codec_executables()
    command = [executables["ffprobe"]["path"], "-v", "error", "-protocol_whitelist", "file,pipe",
               "-f", "mov", "-count_frames", "-show_entries",
               "stream=codec_type,codec_name,width,height,nb_read_frames,r_frame_rate,pix_fmt,sample_rate,channels",
               "-of", "json", artifact["path"]]
    stdout, stderr = await run_media_process(command, 10.0)
    if stderr or len(stdout) > 16384:
        raise ValueError("Authored output frame/audio probe failed")
    streams = json.loads(stdout).get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if len(streams) != 2 or len(video) != 1 or len(audio) != 1:
        raise ValueError("Authored output requires exactly one video and one audio stream")
    v, a = video[0], audio[0]
    if (v.get("codec_name"), v.get("width"), v.get("height"), v.get("nb_read_frames"),
            v.get("r_frame_rate"), v.get("pix_fmt")) != ("h264", 1280, 720, "30", "30/1", "yuv420p"):
        raise ValueError("Authored output differs from frozen 30-frame composition")
    if (a.get("codec_name"), a.get("sample_rate"), a.get("channels")) != ("aac", "48000", 2):
        raise ValueError("Authored output requires AAC 48kHz stereo audio")
    if codec_executables() != executables or not verify_output(artifact):
        raise ValueError("Authored output or codec executable changed during qualification")
    return {"frames": 30, "fps": 30, "audio_codec": "aac", "audio_sample_rate": 48000,
            "audio_channels": 2, "receipt": receipt, "playback_verified": False,
            "capability": "bounded solid-card fixture only; production storyboards unsupported"}
