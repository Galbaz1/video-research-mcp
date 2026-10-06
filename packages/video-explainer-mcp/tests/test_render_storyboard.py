"""Source-only production projection and meaningful refusal boundaries."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from video_explainer_mcp.render_storyboard import production_project
from video_explainer_mcp import render_storyboard_sources as sources


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def _pins(project: Path) -> dict:
    return {
        path.relative_to(project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in project.rglob("*")
        if path.is_file()
    }


@pytest.fixture
def production(tmp_path):
    project = tmp_path / "project"
    for name in ("storyboard", "scenes/nested", "voiceover"):
        (project / name).mkdir(parents=True, exist_ok=True)
    _write(project / "config.json", {"paths": {"storyboard": "storyboard/storyboard.json"}})
    board = {
        "title": "Two authored types",
        "video": {"width": 1920, "height": 1080, "fps": 30},
        "style": {},
        "audio": {"background_music": None, "music_volume": 0.1},
        "total_duration_seconds": 0.4,
        "scenes": [
            {
                "id": "first",
                "type": "chart",
                "title": "Observed values",
                "audio_file": "voiceover/first.wav",
                "audio_duration_seconds": 0.1,
                "visual_padding_seconds": 0.2,
                "scene_buffer_seconds": 0,
                "sfx_cues": [],
                "props": {"values": [2, 5], "label": "Measured"},
            },
            {
                "id": "second",
                "type": "quote",
                "title": "Source words",
                "audio_file": "voiceover/second.mp3",
                "audio_duration_seconds": 0.07,
                "visual_padding_seconds": 0.03,
                "props": {"text": "An independent claim"},
            },
        ],
    }
    _write(project / "storyboard/storyboard.json", board)
    (project / "scenes/index.ts").write_text(
        "import {Chart} from './Chart'; import {Quote} from './nested/Quote';\n"
        "export const sceneRegistry = {chart: Chart, quote: Quote};\n"
    )
    (project / "scenes/Chart.tsx").write_text(
        "export const Chart = ({scene}) => scene.props.values;\n"
    )
    (project / "scenes/nested/Quote.tsx").write_text(
        "export const Quote = ({scene}) => scene.props.text;\n"
    )
    # These opaque unit bytes test custody only, never media decoding or rendering.
    (project / "voiceover/first.wav").write_bytes(b"first-source-only-audio")
    (project / "voiceover/second.mp3").write_bytes(b"second-source-only-audio")
    return project, board


@pytest.mark.parametrize(
    "resolution,dimensions",
    [
        ("720p", (1280, 720)),
        ("1080p", (1920, 1080)),
        ("4k", (3840, 2160)),
    ],
)
def test_two_types_data_and_audio_tail_share_one_integer_clock(production, resolution, dimensions):
    project, board = production
    frozen = _pins(project)
    result = production_project(project, resolution, frozen)
    props = result["input_props"]
    assert (props["width"], props["height"]) == dimensions
    assert props["fps"] == 30 and props["durationInFrames"] == 12
    first, second = props["scenes"]
    assert [scene["type"] for scene in props["scenes"]] == ["chart", "quote"]
    assert first["props"] == {"values": [2, 5], "label": "Measured"}
    assert second["props"] == {"text": "An independent claim"}
    assert (
        first["from"],
        first["durationInFrames"],
        first["audioDurationInFrames"],
        first["visualPaddingInFrames"],
    ) == (0, 9, 3, 6)
    assert (
        second["from"],
        second["durationInFrames"],
        second["audioDurationInFrames"],
        second["visualPaddingInFrames"],
    ) == (9, 3, 3, 1)
    assert second["from"] + second["durationInFrames"] == 12
    assert first["audio_src"] == "voiceover/first.wav"
    assert second["audio_src"] == "voiceover/second.mp3"
    assert result["project_sha256"] == frozen
    assert set(result["scene_source_sha256"]) == {
        "scenes/index.ts",
        "scenes/Chart.tsx",
        "scenes/nested/Quote.tsx",
    }
    assert set(result["asset_pins"]) == {"voiceover/first.wav", "voiceover/second.mp3"}
    assert result["scene_source_root"] == str(project / "scenes")
    assert result["scene_registry_path"] == str(project / "scenes/index.ts")
    assert result["storyboard_metadata"]["title"] == board["title"]
    assert result["expected_output"] == str(project / f"output/final-{resolution}.mp4")
    assert not (project / "output").exists()
    assert _pins(project) == frozen


@pytest.mark.parametrize(
    "field,value",
    [
        ("audio_duration_seconds", 0),
        ("audio_duration_seconds", -1),
        ("audio_duration_seconds", True),
        ("audio_duration_seconds", "1"),
        ("audio_duration_seconds", float("inf")),
        ("audio_duration_seconds", float("nan")),
        ("visual_padding_seconds", -0.1),
        ("visual_padding_seconds", False),
        ("scene_buffer_seconds", 0.1),
        ("sfx_cues", [{"file": "boom.wav"}]),
        ("sfx_cues", None),
        ("audio_volume", 0.5),
        ("transition", "fade"),
        ("from", 0),
        ("durationInFrames", 999),
        ("props", []),
        ("type", ""),
        ("id", " "),
        ("title", None),
    ],
)
def test_unsupported_scene_controls_and_clocks_refuse(production, field, value):
    project, board = production
    board["scenes"][0][field] = value
    _write(project / "storyboard/storyboard.json", board)
    with pytest.raises(ValueError):
        production_project(project, "720p", _pins(project))


@pytest.mark.parametrize(
    "path",
    [
        "../outside.wav",
        "/tmp/outside.wav",
        "voiceover/../first.wav",
        "voiceover//first.wav",
        "https://example.test/audio.wav",
        "file:///tmp/audio.wav",
        "voiceover\\first.wav",
        "./voiceover/first.wav",
        "",
        "config.json",
        None,
    ],
)
def test_audio_path_escape_and_non_audio_inputs_refuse(production, path):
    project, board = production
    board["scenes"][0]["audio_file"] = path
    _write(project / "storyboard/storyboard.json", board)
    with pytest.raises(ValueError):
        production_project(project, "720p", _pins(project))


@pytest.mark.parametrize(
    "damage",
    [
        "fps",
        "music",
        "audio_option",
        "style",
        "board_option",
        "total",
        "dimensions",
        "duplicate",
        "empty",
        "too_many",
    ],
)
def test_board_controls_identity_and_limits_refuse(production, damage):
    project, board = production
    if damage == "fps":
        board["video"]["fps"] = 24
    elif damage == "music":
        board["audio"]["background_music"] = "voiceover/first.wav"
    elif damage == "audio_option":
        board["audio"]["fade_out_seconds"] = 0.2
    elif damage == "style":
        board["style"] = {"background": "red"}
    elif damage == "board_option":
        board["transitions"] = "fade"
    elif damage == "total":
        board["total_duration_seconds"] = 0.41
    elif damage == "dimensions":
        board["video"]["height"] = 721
    elif damage == "duplicate":
        board["scenes"][1]["id"] = "first"
    elif damage == "empty":
        board["scenes"] = []
    else:
        board["scenes"] = [dict(board["scenes"][0], id=str(i)) for i in range(65)]
    _write(project / "storyboard/storyboard.json", board)
    with pytest.raises(ValueError):
        production_project(project, "720p", _pins(project))


def test_64_scenes_use_exact_cumulative_ceilings_and_bound_total_frames(production):
    project, board = production
    (project / "voiceover/second.mp3").unlink()
    board.pop("total_duration_seconds")
    scene = board["scenes"][0]
    board["scenes"] = [
        dict(scene, id=str(i), audio_duration_seconds=28.125, visual_padding_seconds=0)
        for i in range(64)
    ]
    _write(project / "storyboard/storyboard.json", board)
    # Raw seconds fit exactly, but per-scene ceil would exceed 30 minutes by 16 frames.
    with pytest.raises(ValueError, match="54000"):
        production_project(project, "720p", _pins(project))
    for value in board["scenes"]:
        value["audio_duration_seconds"] = 28.1
    _write(project / "storyboard/storyboard.json", board)
    props = production_project(project, "720p", _pins(project))["input_props"]
    assert len(props["scenes"]) == 64 and props["durationInFrames"] == 53952
    assert [value["from"] for value in props["scenes"]] == list(range(0, 53952, 843))


def test_tiny_positive_tail_is_not_lost_by_decimal_context(production):
    project, board = production
    (project / "voiceover/second.mp3").unlink()
    board.pop("total_duration_seconds")
    board["scenes"] = [
        dict(board["scenes"][0], audio_duration_seconds=1, visual_padding_seconds=1e-100)
    ]
    _write(project / "storyboard/storyboard.json", board)
    props = production_project(project, "720p", _pins(project))["input_props"]
    assert props["durationInFrames"] == 31
    assert props["scenes"][0]["audioDurationInFrames"] == 30
    assert props["scenes"][0]["visualPaddingInFrames"] == 1


@pytest.mark.parametrize(
    "name",
    [
        "config.json",
        "storyboard/storyboard.json",
        "scenes/index.ts",
        "scenes/nested/Quote.tsx",
        "voiceover/second.mp3",
    ],
)
def test_changed_frozen_input_is_refused(production, name):
    project, _ = production
    frozen = _pins(project)
    with (project / name).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError, match="hash changed"):
        production_project(project, "720p", frozen)


@pytest.mark.parametrize("damage", ["missing", "extra", "invalid", "new_source", "missing_index"])
def test_external_freeze_is_an_exact_set_not_an_assertion(production, damage):
    project, _ = production
    frozen = _pins(project)
    if damage == "missing":
        frozen.pop("scenes/nested/Quote.tsx")
    elif damage == "extra":
        frozen["unadmitted.ts"] = "a" * 64
    elif damage == "invalid":
        frozen["scenes/index.ts"] = "operator says granted"
    elif damage == "new_source":
        (project / "scenes/new.ts").write_text("export const changed = true;")
    else:
        (project / "scenes/index.ts").unlink()
    with pytest.raises(ValueError):
        production_project(project, "720p", frozen)


@pytest.mark.parametrize(
    "name",
    [
        "config.json",
        "storyboard",
        "voiceover",
        "voiceover/first.wav",
        "scenes",
        "scenes/nested",
        "scenes/Chart.tsx",
        "output",
    ],
)
def test_symlink_components_are_refused_even_for_internal_targets(production, name):
    project, _ = production
    frozen = _pins(project)
    path = project / name
    original = project / (path.name + "-original")
    if path.exists():
        path.rename(original)
    else:
        original.mkdir()
    path.symlink_to(original, target_is_directory=original.is_dir())
    with pytest.raises((ValueError, OSError)):
        production_project(project, "720p", frozen)


def test_unreadable_nested_directory_cannot_be_omitted(production, monkeypatch):
    project, _ = production
    frozen = _pins(project)
    scan = os.scandir

    def deny_nested(path):
        if Path(path) == project / "scenes/nested":
            raise PermissionError("source directory deliberately unreadable")
        return scan(path)

    monkeypatch.setattr(sources.os, "scandir", deny_nested)
    with pytest.raises(PermissionError, match="deliberately unreadable"):
        production_project(project, "720p", frozen)


@pytest.mark.parametrize("path", ["../outside.mp4", "/tmp/outside.mp4", "output/custom.mp4"])
def test_configured_output_escape_or_unimplemented_route_refuses(production, path):
    project, _ = production
    _write(project / "config.json", {"paths": {"final_video": path}})
    with pytest.raises(ValueError, match="final_video"):
        production_project(project, "720p", _pins(project))


@pytest.mark.parametrize("name", ["output/final-720p.mp4", "output/final-720p.mp4.receipt.json"])
def test_retained_output_is_refused_without_overwrite(production, name):
    project, _ = production
    frozen = _pins(project)
    path = project / name
    path.parent.mkdir()
    path.write_bytes(b"retained")
    with pytest.raises(ValueError, match="fresh"):
        production_project(project, "720p", frozen)
    assert path.read_bytes() == b"retained"


@pytest.mark.parametrize(
    "name,limit",
    [
        ("config.json", 1024 * 1024),
        ("scenes/Chart.tsx", 1024 * 1024),
        ("voiceover/first.wav", 64 * 1024 * 1024),
    ],
)
def test_oversize_inputs_refuse_before_unbounded_read(production, name, limit):
    project, _ = production
    frozen = _pins(project)
    with (project / name).open("r+b") as stream:
        stream.truncate(limit + 1)
    with pytest.raises(ValueError, match="byte ceiling"):
        production_project(project, "720p", frozen)


def test_non_typescript_scene_source_cannot_escape_closure(production):
    project, _ = production
    (project / "scenes/unsealed.js").write_text("export const unseen = 1;")
    with pytest.raises(ValueError, match="only .ts/.tsx"):
        production_project(project, "720p", _pins(project))


def test_numeric_overflow_in_registry_props_refuses_before_projection(production):
    project, board = production
    board["scenes"][0]["props"] = {"value": "overflow"}
    body = json.dumps(board).replace('"overflow"', "1e999")
    (project / "storyboard/storyboard.json").write_text(body)
    with pytest.raises(ValueError, match="JSON"):
        production_project(project, "720p", _pins(project))


@pytest.mark.parametrize(
    "value", [2**53 - 1, -(2**53 - 1), float(2**53 - 1), -float(2**53 - 1), 0, False, 0.125]
)
def test_nested_props_safe_integer_edges_preserve_values(production, value):
    project, board = production
    payload = {"nested": [{"points": [value, {"label": "source data"}]}]}
    board["scenes"][0]["props"] = payload
    _write(project / "storyboard/storyboard.json", board)
    result = production_project(project, "720p", _pins(project))
    assert result["input_props"]["scenes"][0]["props"] == payload


@pytest.mark.parametrize(
    "value", [2**53, -(2**53), 2**53 + 1, -(2**53 + 1), float(2**53), -float(2**53), 1e20, -1e20]
)
def test_nested_props_unsafe_signed_integer_or_integral_float_refuses(production, value):
    project, board = production
    board["scenes"][0]["props"] = {"nested": [{"points": [0.125, {"value": value}]}]}
    _write(project / "storyboard/storyboard.json", board)
    with pytest.raises(ValueError, match="Scene props.*safe integer"):
        production_project(project, "720p", _pins(project))
