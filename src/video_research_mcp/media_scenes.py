"""Bounded hard visual cuts and source-relative contiguous scene intervals."""

from .config import get_config
from .media_frames import _actual_seconds, _pts, _source_clock
from .media_image_read import decode_command, geometry
from .media_probe import probe_snapshot
from .media_process import run_media_process
from .media_snapshot import snapshot
from .models.scene_assets import SceneRequest


def _window(source, request):
    """Reject outside or overlong windows instead of silently clamping source selection."""
    extent, offset = _source_clock(source)
    start = request.start_seconds
    end = extent if request.end_seconds is None else request.end_seconds
    if not 0 <= start < end <= extent:
        raise ValueError("Scene window is outside the source presentation extent")
    if end - start > 120:
        raise ValueError("Scene window exceeds the120-second detection limit")
    return start, end, offset


async def _detect(owned, source, request, start, end, offset):
    """Scale deterministically, retaining only genuine named original-clock cut records."""
    _, _, transform = geometry(source, 16384, None)
    expression = f"gt(t,{start + offset:.12f})*lt(t,{end + offset:.12f})*gt(scene,{request.threshold})"
    command = decode_command(owned, source, before_input=["-ss", str(start), "-t", str(end - start + 1)])
    command.extend(["-vf", f"{transform},select='{expression}',showinfo", "-frames:v", str(request.max_cuts + 1),
                    "-fps_mode", "passthrough", "-f", "null", "-"])
    _, stderr = await run_media_process(command, owned.remaining())
    clock, points = _pts(stderr, source["time_base"])
    if len(points) > request.max_cuts:
        raise ValueError("Visual scene cut budget exceeded; no complete partition was established")
    cuts = [{"raw_cut_index": index, "original_pts": pts, "time_base": clock,
             "actual_seconds": _actual_seconds(pts, clock, source)} for index, pts in points.items()]
    if any(not start < cut["actual_seconds"] < end for cut in cuts):
        raise ValueError("Visual cut PTS is outside the requested half-open window")
    if any(b["actual_seconds"] <= a["actual_seconds"] for a, b in zip(cuts, cuts[1:])):
        raise ValueError("Visual cut PTS is not strictly chronological")
    return cuts


def _partition(raw, start, end, minimum):
    """Merge short internal and final intervals without synthesizing a source cut point."""
    retained, previous = [], start
    for cut in raw:
        if cut["actual_seconds"] - previous + 1e-9 >= minimum:
            retained.append(cut)
            previous = cut["actual_seconds"]
    if retained and end - retained[-1]["actual_seconds"] + 1e-9 < minimum:
        retained.pop()
    boundaries = [start, *[cut["actual_seconds"] for cut in retained], end]
    scenes = [{"scene_index": index, "start_seconds": a, "end_seconds": b,
               "duration_seconds": b - a, "half_open": True}
              for index, (a, b) in enumerate(zip(boundaries, boundaries[1:]))]
    return retained, scenes


async def detect_scenes(request: SceneRequest) -> dict:
    """Return actual-PTS hard-cut intervals; overflow never returns a complete partition."""
    request = SceneRequest.model_validate(request)
    async with snapshot(request.file_path, request.expected_source_sha256) as owned:
        source = await probe_snapshot(owned)
        start, end, offset = _window(source, request)
        raw = await _detect(owned, source, request, start, end, offset)
        cuts, scenes = _partition(raw, start, end, request.min_scene_seconds)
        return {"operation": "visual_scene_detection", "source": source,
                "window": {"start_seconds": start, "end_seconds": end},
                "raw_cuts": raw, "cuts": cuts, "scenes": scenes, "status": "complete",
                "coverage": {"requested_window": {"start_seconds": start, "end_seconds": end},
                             "visual_detection_complete": True, "watched_intervals": []},
                "algorithm": {"name": "ffmpeg_visual_scene_threshold", "version": 1,
                              "threshold": request.threshold, "min_scene_seconds": request.min_scene_seconds,
                              "comparison_grid_max_pixels": 16384, "raw_cut_count": len(raw),
                              "retained_cut_count": len(cuts), "suppressed_cut_count": len(raw) - len(cuts)},
                "provenance": {"semantic_scenes_verified": False, "full_stream_validation": False,
                               "interval_boundaries": "requested_endpoints_and_original_decoded_cut_pts",
                               "source_unchanged_verified": True},
                "limits": {"max_window_seconds": 120, "max_cuts": request.max_cuts,
                           "cut_overflow": "explicit_failure_no_complete_partition",
                           "max_single_allocation_bytes": 67108864, "process_rss_bound": None,
                           "process_stream_output_bytes_each": 1048576,
                           "overall_timeout_seconds": get_config().media_acquire_timeout_seconds}}
