"""First-party motion units using qualified root Pillow/NumPy and original-expert stubs.

These tests do not import Qwen or qualify the blocked selected spatial runtime.
"""

import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from tests.test_spatial_inputs import build_inputs

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import spatial_motion as sm  # noqa: E402


def planes(values):
    return [np.full((3, 4), value, dtype=np.float32) for value in values]


def test_normalized_changes_runs_and_original_ids():
    """GIVEN two consecutive full changes WHEN segmented THEN inclusive run and clock IDs survive."""
    result = sm.segment(planes([0, 255, 0, 0, 255]), [101, 205, 309, 413, 517], np, threshold=0.5)
    assert result["motion_per_frame"] == [0, 1, 1, 0, 1]
    assert result["clips"] == [[1, 2]]
    assert result["source_clips"] == [[205, 309]]
    assert result["moving_ratio"] == 0.6  # The initial still frame remains in the denominator.
    assert "appearance change" in result["interpretation"]


def test_threshold_is_strict_and_minimum_run_is_two():
    exact = sm.segment(planes([0, 255, 0]), [1, 2, 3], np, threshold=1.0)
    assert exact["moving_ratio"] == 0 and exact["clips"] == []
    isolated = sm.segment(planes([0, 255, 255]), [1, 2, 3], np, threshold=0.5)
    assert isolated["moving_ratio"] == 0.333 and isolated["clips"] == []


def test_automatic_threshold_and_short_still_sequence():
    result = sm.segment(planes([0, 51, 153, 153, 0]), [1, 2, 3, 4, 5], np)
    assert result["motion_threshold"] == pytest.approx(0.14)
    assert result["clips"] == [[1, 2]] and result["moving_ratio"] == 0.6
    still = sm.segment(planes([10]), [501], np)
    assert still["motion_threshold"] == 0.02 and still["motion_per_frame"] == [0]
    assert still["source_frame_ids"] == [501] and still["moving_ratio"] == 0


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_threshold_must_be_finite_normalized(threshold):
    with pytest.raises(ValueError):
        sm.segment(planes([0, 20]), [1, 2], np, threshold)


def test_pillow_luminance_float_subtraction_and_bilinear_resize(tmp_path):
    paths = []
    for index, (size, color) in enumerate([((4, 3), (255, 0, 0)), ((2, 2), (0, 0, 0))]):
        path = tmp_path / f"rgb-{index}.png"
        Image.new("RGB", size, color).save(path)
        paths.append(str(path))
    grays = sm.gray_frames(paths, np, Image)
    assert all(gray.shape == (3, 4) and gray.dtype == np.float32 for gray in grays)
    assert np.all(grays[0] == 76) and np.all(grays[1] == 0)
    assert np.mean(grays[1] - grays[0]) == -76  # No uint8 wraparound.
    result = sm.segment(grays, [101, 205], np, threshold=0)
    assert result["motion_per_frame"] == [0, round(76 / 255, 4)]
    assert "differs from OpenCV" in result["conversion"]


def test_pillow_resize_uses_the_declared_bilinear_kernel(tmp_path):
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    Image.new("L", (4, 4), 0).save(first)
    image = Image.new("L", (2, 2))
    image.putdata([0, 255, 255, 0])
    image.save(second)
    actual = sm.gray_frames([str(first), str(second)], np, Image)[1]
    expected = np.asarray(image.resize((4, 4), Image.Resampling.BILINEAR), dtype=np.float32)
    assert np.array_equal(actual, expected) and 0 < actual[1, 1] < 255


def test_segmentation_handle_uses_only_authorized_image_paths(tmp_path):
    inputs, _, scene = build_inputs(tmp_path)
    imported = []
    def imports(name):
        imported.append(name)
        assert name in ("numpy", "PIL.Image")
        return importlib.import_module(name)
    result = json.loads(sm.handle({"frames": scene["frames"], "motion_threshold": 0}, inputs, imports)[0]["text"])
    assert result["source_frame_ids"] == [101, 205, 309] and result["clips"] == [[1, 2]]
    assert imported == ["numpy", "PIL.Image"]
    with pytest.raises(ValueError, match="outside"):
        sm.handle({"frames": [str(tmp_path / "other.png")]}, inputs, imports)


def test_original_point_expert_result_is_flat_and_complete():
    called = []
    class Expert:
        @staticmethod
        def predict_trajectory(points, n_future, order):
            called.append((points, n_future, order))
            return {"future_points": [[3, 4], [4, 5]], "method": "polynomial"}
    result = sm.predict({"past_points": [[1, 2], [2, 3]], "n_future": 2, "order": 1}, Expert)
    assert called == [([[1, 2], [2, 3]], 2, 1)]
    assert result["future_points"] == [[3, 4], [4, 5]] and result["method"] == "polynomial"
    assert not isinstance(result["future_points"], dict)
    module = SimpleNamespace(MotionExpert=Expert)
    handled = json.loads(sm.handle({"past_points": [[1, 2], [2, 3]], "n_future": 2, "order": 1}, None, lambda _: module)[0]["text"])
    assert handled == result


@pytest.mark.parametrize("arguments", [
    {"past_points": []}, {"past_points": [[1, 2]]}, {"past_points": [[1], [2]]},
    {"past_points": [[1, 2], [2, 3, 4]]}, {"past_points": [[1, float("nan")], [2, 3]]},
    {"past_points": [[1, 2], [2, 3]], "n_future": 33},
    {"past_points": [[1, 2], [2, 3]], "order": 6},
    {"past_points": [[1, 2], [2, 3]], "n_future": True},
])
def test_prediction_bounds_refuse_before_original_expert(arguments):
    class Never:
        @staticmethod
        def predict_trajectory(*a, **k):
            pytest.fail("invalid point prediction dispatched")
    with pytest.raises(ValueError):
        sm.predict(arguments, Never)


@pytest.mark.parametrize("result", [None, {"future_points": {}}, {"future_points": []},
                                      {"future_points": [[float("inf"), 3]]}, {"future_points": [[1, 2, 3]]}])
def test_incomplete_or_nonfinite_original_prediction_is_not_completion(result):
    class Expert:
        @staticmethod
        def predict_trajectory(*a, **k):
            return result
    with pytest.raises(ValueError):
        sm.predict({"past_points": [[0, 1], [1, 2]], "n_future": 1}, Expert)
