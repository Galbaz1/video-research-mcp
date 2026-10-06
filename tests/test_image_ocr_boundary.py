"""Native geometry precision boundaries retain original coordinates without clipping."""

import copy

import pytest

from video_research_mcp.image_ocr import map_observation
from video_research_mcp.models.image_ocr import OCRObservation

EPSILON = 2**-24
IDENTITY = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
PREPARATION = {"artifact": {"width": 640, "height": 112}, "transforms": {
    "oriented_to_output": IDENTITY, "output_to_source": IDENTITY,
}}


def observation(left=0.2, bottom=0.2, right=0.8, top=0.8):
    return {"kind": "line", "text": "EXACT", "confidence": 1,
            "raw_box": [left, bottom, right-left, top-bottom],
            "raw_points": [[left, top], [right, top], [right, bottom], [left, bottom]]}


@pytest.mark.parametrize("edge", ["left", "right", "top", "bottom"])
@pytest.mark.parametrize("overshoot", [EPSILON / 2, EPSILON])
def test_native_precision_all_edges_keep_exact_backend_and_mapping(edge, overshoot):
    bounds = {"left": 0.0, "bottom": 0.0, "right": 1.0, "top": 1.0}
    bounds[edge] += -overshoot if edge in {"left", "bottom"} else overshoot
    value = observation(**bounds)
    original = copy.deepcopy(value)
    result = map_observation(value, PREPARATION, native=True)
    assert value == original
    assert result["raw_box"] == original["raw_box"]
    assert result["raw_points"] == original["raw_points"]
    expected = [[x * 640, (1-y) * 112] for x, y in original["raw_points"]]
    assert result["prepared_points"] == expected
    assert result["oriented_points"] == expected
    assert result["stored_points"] == expected
    boundary = result["geometry_boundary"]
    assert boundary["policy"] == "native_normalized_precision"
    assert boundary["normalized_epsilon"] == EPSILON
    pixel_edge = edge
    scale = 640 if edge in {"left", "right"} else 112
    assert boundary[pixel_edge + "_pixels"] == overshoot * scale


@pytest.mark.parametrize("edge", ["left", "right", "top", "bottom"])
def test_native_just_outside_precision_allowance_refuses(edge):
    bounds = {"left": 0.0, "bottom": 0.0, "right": 1.0, "top": 1.0}
    bounds[edge] += -EPSILON*2 if edge in {"left", "bottom"} else EPSILON*2
    with pytest.raises(ValueError, match="outside"):
        map_observation(observation(**bounds), PREPARATION, native=True)


def test_non_native_bounds_remain_exact():
    value = observation(left=-EPSILON / 2, right=10, top=10)
    with pytest.raises(ValueError, match="outside"):
        map_observation(value, PREPARATION, native=False)


@pytest.mark.parametrize("changes", [
    {"raw_box": [0, 0, 0, 1]},
    {"raw_box": [0, 0, 1, float("nan")]},
    {"raw_points": [[0, 0], [0, 0], [0, 0], [0, 0]]},
    {"raw_points": [[0, 0], [0.2, 0.2], [0.4, 0.4], [0.6, 0.6]]},
    {"raw_points": [[0, 0], [1, 1], [0, 1], [1, 0]]},
    {"raw_box": [0, 0, 1, 1], "raw_points": [[0, 0], [1, 1], [0, 1], [0.8, 0]]},
    {"raw_points": [[float("inf"), 0], [1, 0], [1, 1], [0, 1]]},
])
def test_invalid_or_degenerate_geometry_still_refuses(changes):
    with pytest.raises(ValueError):
        map_observation({**observation(), **changes}, PREPARATION, native=True)


def test_exact_bounds_have_zero_overshoot():
    result = map_observation(observation(0, 0, 1, 1), PREPARATION, native=True)
    assert all(result["geometry_boundary"][edge + "_pixels"] == 0
               for edge in ["left", "top", "right", "bottom"])


def test_precision_geometry_maps_crop_resize_and_rotated_source():
    value = observation(left=-EPSILON / 2)
    preparation = {"artifact": {"width": 640, "height": 112}, "transforms": {
        "oriented_to_output": [[2, 0, -112], [0, 2, -384], [0, 0, 1]],
        "output_to_source": [[0, 0.5, 192], [-0.5, 0, 584], [0, 0, 1]],
    }}
    result = map_observation(value, preparation, native=True)
    prepared = [[x * 640, (1-y) * 112] for x, y in value["raw_points"]]
    assert result["prepared_points"] == prepared
    assert result["oriented_points"] == [[x/2+56, y/2+192] for x, y in prepared]
    assert result["stored_points"] == [[y/2+192, 584-x/2] for x, y in prepared]
    assert result["raw_points"] == value["raw_points"]


def test_historical_observation_without_boundary_metadata_remains_readable():
    record = map_observation(observation(), PREPARATION, native=True)
    del record["geometry_boundary"]
    parsed = OCRObservation.model_validate(record)
    assert parsed.geometry_boundary is None
    assert parsed.text == "EXACT"
