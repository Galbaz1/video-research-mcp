"""Full-denominator greedy visual frame similarity with exact source-frame lineage."""

import hashlib
import io

from .config import get_config
from .errors import make_tool_error
from .image_preprocessing import check_worker, image_worker
from .media_frames import _source_clock, frame_at
from .media_image_read import MAX_ARTIFACT_BYTES, MAX_OUTPUT_PIXELS, geometry
from .media_local_io import _open_regular
from .media_probe import probe_snapshot
from .media_snapshot import checked_path, copy_hash, snapshot
from .models.scene_assets import FrameDedupRequest
from .native_media_results import native_operation


def _reserve(source, request):
    """Reserve every submitted candidate before any decoded frame allocation."""
    width, height, _ = geometry(source, request.max_pixels, None)
    pixels = width * height * len(request.times_seconds)
    byte_ceiling = (4 * width * height + 65536) * len(request.times_seconds)
    if pixels > MAX_OUTPUT_PIXELS or byte_ceiling > MAX_ARTIFACT_BYTES:
        raise ValueError("Frame candidates exceed aggregate16M pixel or8MiB artifact reservation")
    return {"reserved_output_pixels": pixels, "reserved_artifact_bytes": byte_ceiling,
            "prepared_dimensions": [width, height]}


def _dhash(frame, cancelled, deadline):
    """Hash one bounded exact PNG byte read using64 horizontal grayscale comparisons."""
    from PIL import Image

    check_worker(cancelled, deadline)
    with _open_regular(checked_path(frame["path"])) as reader:
        data = reader.read(MAX_ARTIFACT_BYTES + 1)
    if len(data) != frame["bytes"] or hashlib.sha256(data).hexdigest() != frame["sha256"]:
        raise ValueError("Frame artifact identity changed before visual hashing")
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or image.size != (frame["width"], frame["height"]):
            raise ValueError("Frame artifact dimensions/format differ from the decoded record")
        gray = image.convert("L")
        try:
            with gray.resize((9, 8), Image.Resampling.BILINEAR) as small:
                values = list(small.get_flattened_data())
        finally:
            gray.close()
    value = 0
    for row in range(8):
        for column in range(8):
            value = (value << 1) | (values[row * 9 + column] > values[row * 9 + column + 1])
    check_worker(cancelled, deadline)
    return value


def _row(index, requested):
    return {"candidate_index": index, "requested_seconds": requested, "decision": "error",
            "frame": None, "dhash_hex": None, "representative_index": None,
            "hamming_distance": None, "error": None}


async def _candidate(index, requested, owned, source, maximum, generated):
    """Keep an explicit row for extent/decode errors and the actual clock of every decoded candidate."""
    row = _row(index, requested)
    try:
        extent, _ = _source_clock(source)
        if requested >= extent:
            raise ValueError("Candidate time is outside the source presentation extent")
        result = await frame_at(str(owned.path), time_seconds=requested, max_pixels=maximum,
                                expected_source_sha256=owned.sha256)
        generated.append(result)
        row["frame"] = result["frames"][0]
        value = await image_worker(_dhash, row["frame"], deadline=owned.deadline)
        row.update(dhash_hex=f"{value:016x}", decision="retained")
        return row, value
    except Exception as exc:
        row["error"] = make_tool_error(exc)
        return row, None


def _decision(row, value, retained, threshold):
    """Use the first chronological retained representative within the requested distance."""
    for index, reference in retained:
        distance = (value ^ reference).bit_count()
        if distance <= threshold:
            row.update(decision="similar", representative_index=index, hamming_distance=distance)
            return
    row.update(representative_index=row["candidate_index"], hamming_distance=0)
    retained.append((row["candidate_index"], value))


async def _verify_frames(frames):
    """Verify every retained/error/similar artifact before returning a successful or partial report."""
    if sum(f["bytes"] for f in frames) > MAX_ARTIFACT_BYTES:
        raise ValueError("Actual candidate artifacts exceed the8MiB aggregate byte budget")
    for frame in frames:
        if await copy_hash(checked_path(frame["path"])) != (frame["sha256"], frame["bytes"]):
            raise ValueError("Candidate frame artifact changed during visual comparison")


async def deduplicate_frames(request: FrameDedupRequest) -> dict:
    """Classify every submitted time without dropping duplicates or invalid source points."""
    request = FrameDedupRequest.model_validate(request)
    async with native_operation() as generated, snapshot(request.file_path, request.expected_source_sha256) as owned:
        source = await probe_snapshot(owned)
        reserved = _reserve(source, request)
        order = sorted(range(len(request.times_seconds)), key=lambda i: (request.times_seconds[i], i))
        candidates, retained = [None] * len(order), []
        for index in order:
            owned.remaining()
            row, value = await _candidate(index, request.times_seconds[index], owned, source, request.max_pixels, generated)
            if value is not None:
                _decision(row, value, retained, request.hamming_threshold)
            candidates[index] = row
        frames = [row["frame"] for row in candidates if row["frame"] is not None]
        await _verify_frames(frames)
        return _result(source, candidates, order, frames, request, reserved)


def _result(source, candidates, order, frames, request, reserved):
    """Keep exact artifacts and lossy visual decisions in the same complete candidate denominator."""
    errors = [row["candidate_index"] for row in candidates if row["decision"] == "error"]
    return {"operation": "visual_frame_dedup", "source": source, "candidates": candidates,
            "decision_order": order, "retained_indices": [row["candidate_index"] for row in candidates if row["decision"] == "retained"],
            "similar_indices": [row["candidate_index"] for row in candidates if row["decision"] == "similar"],
            "error_indices": errors, "frames": frames,
            "artifacts": [{**frame, "mime": "image/png"} for frame in frames],
            "status": "partial" if errors else "complete",
            "coverage": {"candidate_count": len(candidates), "decoded_count": len(frames),
                         "sampled_points": [frame["actual_seconds"] for frame in frames], "watched_intervals": []},
            "algorithm": {"name": "horizontal_grayscale_dhash64", "version": 1,
                          "grid": [9, 8], "resampling": "pillow_bilinear", "bit_test": "left_greater_than_right",
                          "hamming_threshold": request.hamming_threshold, "representative_policy": "first_chronological_match"},
            "provenance": {"identity_equivalence_verified": False, "changed_text_preservation_verified": False,
                           "semantic_similarity_verified": False, "source_unchanged_verified": True},
            "limits": {**reserved, "max_candidates": 64, "requested_max_pixels": request.max_pixels,
                       "max_aggregate_output_pixels": MAX_OUTPUT_PIXELS, "max_artifact_bytes": MAX_ARTIFACT_BYTES,
                       "max_decoded_pixels": 8000000, "max_single_allocation_bytes": 67108864,
                       "process_stream_output_bytes_each": 1048576,
                       "process_rss_bound": None, "overall_timeout_seconds": get_config().media_acquire_timeout_seconds}}
