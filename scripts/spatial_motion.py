"""Owned Pillow/NumPy appearance segmentation and bounded original point prediction.

Pillow L conversion/BILINEAR resampling differs from the original OpenCV path.
This module neither imports nor emulates OpenCV; appearance change is not proof
of object movement, physical tracking or causal motion.
"""

from __future__ import annotations

from spatial_inputs import bounded_int, finite, vector


def gray_frames(paths: list[str], numpy, image_module) -> list:
    """Decode admitted frames as Pillow L and resize with Pillow BILINEAR."""
    grays, size = [], None
    for path in paths:
        with image_module.open(path) as image:
            gray = image.convert("L")
            size = size or gray.size
            if gray.size != size:
                gray = gray.resize(size, resample=image_module.Resampling.BILINEAR)
            grays.append(numpy.asarray(gray, dtype=numpy.float32))
    return grays


def segment(grays: list, frame_ids: list[int], numpy, threshold=None) -> dict:
    """Compute normalized differences and inclusive runs under the fixed appearance contract."""
    if len(grays) != len(frame_ids):
        raise ValueError("Motion frames and source IDs must align")
    if threshold is not None:
        finite(threshold, "motion_threshold")
        if not 0 <= threshold <= 1:
            raise ValueError("motion_threshold must lie in 0..1")
    motion = [0.0] if grays else []
    for current, previous in zip(grays[1:], grays):
        motion.append(float(numpy.mean(numpy.abs(current - previous)) / 255.0))
    if any(not 0 <= finite(value, "appearance difference") <= 1 for value in motion):
        raise ValueError("Decoded grayscale difference is outside the normalized range")
    threshold = threshold if threshold is not None else max(0.02, float(numpy.percentile(motion, 60)) * 0.5) if motion else 0.02
    moving = [value > threshold for value in motion]
    clips, start = [], None
    for index, active in enumerate(moving + [False]):
        if active and start is None:
            start = index
        elif not active and start is not None:
            if index - start >= 2:
                clips.append([start, index - 1])
            start = None
    return {"num_frames": len(grays), "motion_per_frame": [round(x, 4) for x in motion],
            "motion_threshold": round(threshold, 4), "clips": clips,
            "source_frame_ids": frame_ids,
            "source_clips": [[frame_ids[a], frame_ids[b]] for a, b in clips],
            "moving_ratio": round(sum(moving) / len(moving), 3) if moving else 0.0,
            "interpretation": "appearance change; camera/lighting/object causes unverified",
            "conversion": "Pillow L -> float32; Pillow BILINEAR resize; differs from OpenCV"}


def validate_prediction(arguments: dict) -> tuple[list, int, int]:
    """Require finite consistent 2D/3D observations and bounded extrapolation steps."""
    points = arguments["past_points"]
    bounded_int(len(points), "past_points", 2, 64)
    dimensions = len(points[0])
    if dimensions not in (2, 3):
        raise ValueError("Point prediction requires consistent 2D or 3D observations")
    points = [vector(point, "past point", dimensions) for point in points]
    future = bounded_int(arguments.get("n_future", 3), "n_future", 1, 32)
    order = bounded_int(arguments.get("order", 2), "order", 1, 5)
    return points, future, order


def predict(arguments: dict, expert) -> dict:
    """Delegate the original polynomial expert and return its actual flat result dict."""
    points, future, order = validate_prediction(arguments)
    result = expert.predict_trajectory(points, n_future=future, order=order)
    if not isinstance(result, dict) or not isinstance(result.get("future_points"), list):
        raise ValueError("Original point expert returned no point-list completion")
    if len(result["future_points"]) != future:
        raise ValueError("Original point expert did not return every requested step")
    for point in result["future_points"]:
        vector(point, "predicted point", len(points[0]))
    return {**result, "interpretation": "polynomial extrapolation at evenly spaced input steps; no physical feasibility or uncertainty"}


def handle(arguments: dict, inputs, import_module) -> list:
    """Execute only the selected original prediction or owned segmentation branch."""
    import json

    if arguments.get("past_points") is not None:
        expert = import_module("qwen_mm_plugins_video_spatio.experts.motion_expert").MotionExpert
        result = predict(arguments, expert)
    else:
        paths = arguments.get("frames") or []
        ids = inputs.frame_ids(paths)
        numpy = import_module("numpy")
        image = import_module("PIL.Image")
        result = segment(gray_frames(paths, numpy, image), ids, numpy, arguments.get("motion_threshold"))
    return [{"type": "text", "text": json.dumps(result, allow_nan=False)}]
