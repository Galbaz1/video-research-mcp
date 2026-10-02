"""Independent finite domain, glyph and visible-layout controls on owned synthetic input."""

import copy
import json

import pytest
from pydantic import ValidationError

from video_research_mcp.education_domain import (caption_lines, curve_equation, curve_value, primitives, source_gate)
from video_research_mcp.education_frames import raster
from video_research_mcp.education_glyphs import cells, display_text
from video_research_mcp.education_page import page_bytes
from video_research_mcp.models.education import LessonSpec


def spec_fixture():
    """Author source data independent of the root's unread actual controller/fixture bytes."""
    texts = ["Check the right triangle.", "Square the reflected input.", "Trace the closed loop."]
    return {"schema_version": 1, "title": "Verifying a diagram against its rule",
            "source": {"problem": "Compare each diagram with its numeric rule.", "authority": "Independent synthetic unit input"},
            "analysis": {"triangle_rule": "AB perpendicular BC; AB=4,BC=3,AC=5", "curve_rule": "square_input_reflection",
                         "circuit_rule": "one_series_cycle"},
            "script": {"transcript": " ".join(texts), "captions": [
                {"scene_id": name, "start_seconds": i * 2, "end_seconds": (i + 1) * 2, "text": texts[i]}
                for i, name in enumerate(["triangle", "curve", "circuit"])]},
            "storyboard": {"scenes": [
                {"id": "triangle", "kind": "geometry", "start_seconds": 0, "end_seconds": 2,
                 "equation": "3^2 + 4^2 = 5^2", "points": {"A": [0, 0], "B": [4, 0], "C": [4, 3]}},
                {"id": "curve", "kind": "curve", "start_seconds": 2, "end_seconds": 4, "equation": "y = (-x)^2",
                 "function": "square", "input_reflection": True, "shift": 0,
                 "samples": [[x / 8, (x / 8) * (x / 8)] for x in range(-16, 17)]},
                {"id": "circuit", "kind": "circuit", "start_seconds": 4, "end_seconds": 6, "equation": "ONE SERIES LOOP",
                 "components": ["battery", "resistor"],
                 "terminals": {"battery.p": [160, 140], "battery.n": [160, 220], "resistor.a": [300, 140], "resistor.b": [380, 140]},
                 "wires": [["battery.p", "resistor.a"], ["resistor.b", "battery.n"]]}]}}


def test_actual_source_predicates_drive_numeric_visible_primitives():
    spec = LessonSpec.model_validate(spec_fixture())
    report = source_gate(spec, {"frames": 288000, "duration_seconds": 6})
    assert report["status"] == "passed" and set(report["gates"]) == {"geometry", "curve", "circuit", "captions"}
    assert report["gates"]["geometry"]["lengths"] == [4, 3, 5]
    assert primitives(spec.storyboard.scenes[0])[0]["points"] == [[80, 240], [320, 240], [320, 60], [80, 240]]
    assert primitives(spec.storyboard.scenes[1])[2]["points"][16] == [320, 240]
    assert primitives(spec.storyboard.scenes[2])[0]["points"] == [[160, 140], [300, 140]]
    assert report["gates"]["circuit"]["terminal_degree"] == {k: 2 for k in spec.storyboard.scenes[2].terminals}


def test_unrendered_source_metadata_preserves_provenance_without_display_glyph_limits():
    data = spec_fixture()
    data["source"] = {"problem": "Measure A→B; keep the diagram fixed.", "authority": "Own source; no speech claim."}
    spec = LessonSpec.model_validate(data)
    report = source_gate(spec, {"frames": 288000, "duration_seconds": 6})
    assert report["status"] == "passed" and spec.source.model_dump() == data["source"]
    page = page_bytes(spec, b"unit-only-audio").decode()
    payload = json.loads(page.split('<script id="lesson-data" type="application/json">')[1].split('</script>')[0])
    assert payload["spec"]["source"] == data["source"]


@pytest.mark.parametrize("defect", ["triangle", "coincident", "curve", "equation", "component", "open", "duplicate_wire", "terminal", "scene", "caption_overlap", "caption_scene", "transcript", "glyph", "overflow"])
def test_failed_or_missing_applicable_domain_and_caption_checks_never_pass(defect):
    data = spec_fixture()
    scenes = data["storyboard"]["scenes"]
    if defect == "triangle":
        scenes[0]["points"]["C"] = [4, 2]
    elif defect == "coincident":
        scenes[0]["points"] = {key: [0, 0] for key in "ABC"}
    elif defect == "curve":
        scenes[1]["samples"][10][1] = 100
    elif defect == "equation":
        scenes[1]["equation"] = "y = -x^2"
    elif defect == "component":
        scenes[2]["components"] = ["resistor", "resistor"]
    elif defect == "open":
        scenes[2]["wires"][1] = ["resistor.b", "battery.p"]
    elif defect == "duplicate_wire":
        scenes[2]["wires"][1] = scenes[2]["wires"][0]
    elif defect == "terminal":
        scenes[2]["terminals"]["battery.n"] = [160, 210]
    elif defect == "scene":
        scenes.pop()
    elif defect == "caption_overlap":
        data["script"]["captions"][0]["end_seconds"] = 2.1
    elif defect == "caption_scene":
        data["script"]["captions"][1]["scene_id"] = "triangle"
    elif defect == "transcript":
        data["script"]["transcript"] += " Changed."
    else:
        data["script"]["captions"][0]["text"] = "汉字" if defect == "glyph" else "X" * 39
        data["script"]["transcript"] = " ".join(c["text"] for c in data["script"]["captions"])
    with pytest.raises((ValueError, ValidationError)):
        source_gate(LessonSpec.model_validate(data), {"frames": 288000, "duration_seconds": 6})


@pytest.mark.parametrize("reflected", [False, True])
@pytest.mark.parametrize("shift", [-1, 0, 1])
def test_six_interactive_states_have_independent_numeric_oracles(reflected, shift):
    assert [curve_value(x, reflected, shift) for x in [-1, 0, 1]] == [(x - shift) * (x - shift) for x in [-1, 0, 1]]
    equation = curve_equation(reflected, shift)
    if reflected and shift == 0:
        assert equation == "y = (-x)^2"
    elif reflected:
        assert "(-(" in equation and "))^2" in equation
    assert "-x^2" not in equation


def test_authored_cell_geometry_and_caption_box_are_separate_from_diagrams():
    spec = LessonSpec.model_validate(spec_fixture())
    assert display_text("x + y = 3") == "X + Y = 3"
    assert len(cells("A")) > 0 and cells(" ") == []
    with pytest.raises(ValueError, match="glyph"):
        display_text("é")
    assert caption_lines("Check the right triangle.") == ["CHECK THE RIGHT TRIANGLE."]
    with raster(spec, 0) as image:
        assert image.getpixel((80, 240)) == (72, 204, 188)
        assert image.getpixel((320, 60)) == (72, 204, 188)
        assert image.getpixel((0, 0)) == (24, 32, 48)
        assert image.getpixel((24, 282)) == (72, 204, 188)
        assert image.getpixel((100, 270)) == (24, 32, 48)
    with raster(spec, 1) as image:
        assert image.getpixel((400, 200)) == (72, 204, 188)
    with raster(spec, 2) as image:
        assert image.getpixel((160, 220)) == (72, 204, 188)


def test_page_embeds_exact_source_cells_audio_and_state_derived_controls():
    spec = LessonSpec.model_validate(spec_fixture())
    page = page_bytes(spec, b"synthetic-WAV-for-page-contract-only").decode()
    payload = json.loads(page.split('<script id="lesson-data" type="application/json">')[1].split('</script>')[0])
    assert payload["spec"] == spec.model_dump(mode="json")
    assert payload["primitives"][0][0]["points"][1] == [320, 240]
    assert "data:audio/wav;base64," in page
    for identity in ["scene-triangle", "scene-curve", "scene-circuit", "seek", "reset", "input-reflection", "shift", "equation", "samples"]:
        assert f'id="{identity}"' in page
    assert "state.reflection=true;state.shift=0;seek(0)" in page
    assert "dataset.points=JSON.stringify(samples)" in page and "state.seconds=audio.currentTime;draw()" in page
    assert "font-family" not in page and "<script src=" not in page and "https://" not in page


@pytest.mark.parametrize("defect", ["extra", "nonfinite", "bool", "unsupported"])
def test_schema_rejects_unbounded_or_arbitrary_lesson_inputs(defect):
    data = copy.deepcopy(spec_fixture())
    if defect == "extra":
        data["eval"] = "execute code"
    elif defect == "nonfinite":
        data["storyboard"]["scenes"][0]["points"]["A"][0] = float("nan")
    elif defect == "bool":
        data["storyboard"]["scenes"][0]["points"]["A"][0] = True
    else:
        data["storyboard"]["scenes"][1]["function"] = "eval"
    with pytest.raises(ValidationError):
        LessonSpec.model_validate(data)
