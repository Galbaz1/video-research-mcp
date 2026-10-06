"""Normalize a frozen production storyboard for its caller-authored scene registry."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from .render_storyboard_sources import (
    MIB,
    confined_path,
    freeze_project,
    project_object,
    scene_sources,
)

DIMENSIONS = {"720p": (1280, 720), "1080p": (1920, 1080), "4k": (3840, 2160)}
SCENE_KEYS = {
    "id",
    "type",
    "title",
    "audio_file",
    "audio_duration_seconds",
    "visual_padding_seconds",
    "scene_buffer_seconds",
    "sfx_cues",
    "props",
}
BOARD_KEYS = {
    "scenes",
    "title",
    "description",
    "version",
    "project",
    "video",
    "style",
    "audio",
    "total_duration_seconds",
    "video_research_plan",
}


def _seconds(value: object, label: str, *, positive: bool) -> Fraction:
    if type(value) not in {int, float}:
        raise ValueError(f"{label} must be a finite number")
    if not 0 <= value <= 1800 or positive and value == 0:
        raise ValueError(
            f"{label} must be finite, {'positive' if positive else 'nonnegative'}, <=1800"
        )
    return Fraction(str(value))


def _frames(seconds: Fraction) -> int:
    return (seconds.numerator * 30 + seconds.denominator - 1) // seconds.denominator


def _check_props_integers(props: dict) -> None:
    """Keep nested scene data exact when serialized into JavaScript numbers."""
    pending: list[object] = [props]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif type(value) is int or type(value) is float and value.is_integer():
            if abs(value) > 2**53 - 1:
                raise ValueError(
                    "Scene props integers must be within the JavaScript safe integer range"
                )


def _scene(value: object, start: int) -> tuple[dict, Fraction]:
    if not isinstance(value, dict) or set(value) - SCENE_KEYS:
        raise ValueError("Unsupported production scene fields; registry data belongs in props")
    for name in ("id", "type"):
        if not isinstance(value.get(name), str) or not value[name].strip():
            raise ValueError(f"Scene {name} must be a nonempty string")
    if not isinstance(value.get("title"), str):
        raise ValueError("Scene title must be a string")
    duration = _seconds(value.get("audio_duration_seconds"), "Audio duration", positive=True)
    padding = _seconds(value.get("visual_padding_seconds", 0), "Visual padding", positive=False)
    buffer = _seconds(value.get("scene_buffer_seconds", 0), "Scene buffer", positive=False)
    if buffer != 0:
        raise ValueError("Nonzero scene_buffer_seconds is unsupported; declare visual padding")
    if value.get("sfx_cues", []) != []:
        raise ValueError("Nonempty or malformed sfx_cues are unsupported")
    if "props" in value and not isinstance(value["props"], dict):
        raise ValueError("Scene props must be a JSON object")
    if "props" in value:
        _check_props_integers(value["props"])
    # Exact decimal fractions avoid float addition and precision-dependent rounding.
    seconds = duration + padding
    normalized = {
        "id": value["id"],
        "type": value["type"],
        "title": value["title"],
        "from": start,
        "durationInFrames": _frames(seconds),
        "audio_src": value.get("audio_file"),
        "audioDurationInFrames": _frames(duration),
        "visualPaddingInFrames": _frames(padding),
    }
    if "props" in value:
        normalized["props"] = value["props"]
    return normalized, seconds


def _board_controls(board: dict) -> None:
    """Refuse active controls whose behavior this projection cannot implement."""
    if set(board) - BOARD_KEYS:
        raise ValueError("Unsupported production storyboard fields")
    for key in ("title", "description", "version", "project"):
        if key in board and not isinstance(board[key], str):
            raise ValueError(f"Storyboard {key} must be a string")
    if board.get("style", {}) != {}:
        raise ValueError("Nonempty or malformed global style is unsupported; use scene props")
    video = board.get("video", {})
    if not isinstance(video, dict) or set(video) - {"width", "height", "fps"}:
        raise ValueError("Unsupported production video controls")
    if type(video.get("fps", 30)) is not int or video.get("fps", 30) != 30:
        raise ValueError("Production storyboard requires fps=30")
    if "width" in video or "height" in video:
        dimensions = (video.get("width"), video.get("height"))
        if (
            any(type(item) is not int for item in dimensions)
            or dimensions not in DIMENSIONS.values()
        ):
            raise ValueError("Storyboard dimensions must be a supported resolution pair")
    audio = board.get("audio", {})
    if not isinstance(audio, dict) or set(audio) - {"background_music", "music_volume"}:
        raise ValueError("Unsupported production audio controls")
    if audio.get("background_music") not in (None, ""):
        raise ValueError("Nonempty background music is unsupported")
    if "music_volume" in audio:
        volume = _seconds(audio["music_volume"], "Music volume", positive=False)
        if volume > 1:
            raise ValueError("Music volume must be between zero and one")
    if "video_research_plan" in board and not isinstance(board["video_research_plan"], dict):
        raise ValueError("Storyboard plan lineage must be a JSON object")


def _project_paths(project: Path, resolution: str, config: dict) -> tuple[str, Path]:
    paths = config.get("paths", {})
    if not isinstance(paths, dict):
        raise ValueError("Project paths must be a JSON object")
    storyboard = paths.get("storyboard", "storyboard/storyboard.json")
    if storyboard != "storyboard/storyboard.json":
        raise ValueError("Production requires paths.storyboard=storyboard/storyboard.json")
    output_name = f"output/final-{resolution}.mp4"
    if paths.get("final_video", output_name) != output_name:
        raise ValueError("Production final_video must match the selected confined output")
    output = confined_path(project, output_name)
    if output.parent.exists() and not output.parent.is_dir():
        raise ValueError("Production output parent must be a regular directory")
    for name in (output_name, output_name + ".receipt.json"):
        if confined_path(project, name).exists():
            raise ValueError("Production render requires a fresh output and receipt")
    return storyboard, output


def _timeline(board: dict, project: Path) -> tuple[list[dict], int]:
    values = board.get("scenes")
    if not isinstance(values, list) or not 1 <= len(values) <= 64:
        raise ValueError("Production storyboard requires 1..64 scenes")
    normalized = []
    seconds = Fraction(0)
    end = 0
    ids = set()
    for value in values:
        scene, span = _scene(value, end)
        if scene["id"] in ids:
            raise ValueError("Production scene IDs must be unique")
        ids.add(scene["id"])
        audio = confined_path(project, scene["audio_src"])
        if audio.suffix.lower() not in {
            ".wav",
            ".mp3",
            ".m4a",
            ".aac",
            ".ogg",
            ".flac",
            ".opus",
        }:
            raise ValueError("Selected audio must have a local audio file extension")
        end += scene["durationInFrames"]
        seconds += span
        normalized.append(scene)
    if seconds > 1800 or end > 54000:
        raise ValueError("Production timeline exceeds 1800 seconds / 54000 frames")
    if "total_duration_seconds" in board:
        declared = _seconds(board["total_duration_seconds"], "Total duration", positive=True)
        if declared != seconds:
            raise ValueError("Declared total duration differs from the scene clock")
    return normalized, end


def production_project(project: Path, resolution: str, project_sha256: dict) -> dict:
    """Return a source-only production projection of an externally frozen project.

    Args:
        project: Existing nonsymlink project directory.
        resolution: Selected 720p, 1080p or 4k output dimensions at 30 fps.
        project_sha256: External exact closure of config, board, sources and audio.

    Returns:
        Confined paths, integer scene clock, source/asset pins and registry root.

    Raises:
        ValueError: Unsupported controls, unsafe paths, clock or freeze mismatch.
        OSError: Required regular inputs or source directories cannot be read.
    """
    project = project.absolute()
    if project.resolve(strict=True) != project or not project.is_dir():
        raise ValueError("Production project must be a regular nonsymlink directory")
    if resolution not in DIMENSIONS:
        raise ValueError("Production resolution must be 720p, 1080p or 4k")
    config, config_pin = project_object(project, "config.json")
    board_name, output = _project_paths(project, resolution, config)
    board, board_pin = project_object(project, board_name)
    if config_pin["size_bytes"] + board_pin["size_bytes"] > MIB:
        raise ValueError("Production project JSON exceeds the 1 MiB total byte ceiling")
    _board_controls(board)
    scenes, frames = _timeline(board, project)
    sources = scene_sources(project)
    assets = {scene["audio_src"] for scene in scenes}
    revisions = freeze_project(
        project,
        project_sha256,
        {"config.json": config_pin, board_name: board_pin},
        sources,
        assets,
    )
    width, height = DIMENSIONS[resolution]
    return {
        "storyboard_path": str(project / board_name),
        "expected_output": str(output),
        "input_props": {
            "width": width,
            "height": height,
            "fps": 30,
            "durationInFrames": frames,
            "scenes": scenes,
        },
        "scene_source_root": str(project / "scenes"),
        "scene_registry_path": str(project / "scenes/index.ts"),
        "scene_source_sha256": {name: revisions[name]["sha256"] for name in sources},
        "asset_pins": {name: revisions[name] for name in sorted(assets)},
        "project_sha256": {name: revisions[name]["sha256"] for name in sorted(revisions)},
        "storyboard_metadata": {key: value for key, value in board.items() if key != "scenes"},
    }
