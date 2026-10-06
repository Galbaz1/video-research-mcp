"""Bounded local OCR point tracks with original clocks and receipt-only speech."""

import asyncio
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
import re

from .config import get_config
from .errors import ToolError, make_tool_error
from .image_manifest import MAX_MANIFEST_BYTES
from .image_ocr import recognize_image
from .image_vision import MAX_RAW_BYTES
from .media_snapshot import checked_path, copy_hash
from .models.image_ocr import ImageOCRRequest
from .models.native_media import NativeCoverage
from .models.video_evidence import (
    NumericObservation,
    NumericReversal,
    OCRTimelinePoint,
    TemporalOCRRequest,
    TemporalOCRResult,
    TimelineOCR,
    TimelineSpeech,
)
from .native_media_results import _discard_views

DEADLINE_SECONDS = 300
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


def _error(exc):
    value = make_tool_error(exc)
    value.update(
        retryable=False,
        hint="Inspect retained point evidence; no automatic retry or model fallback",
    )
    if isinstance(exc, ImportError):
        value["category"] = "DEPENDENCY_MISSING"
    elif isinstance(exc, ValueError):
        value["category"] = "SCHEMA_VALIDATION_FAILED"
    return ToolError.model_validate(value)


def _number(ocr):
    indices = [i for i, value in enumerate(ocr.observations) if value.kind == "line"]
    if len(indices) != 1:
        return NumericObservation(
            status="ambiguous" if indices else "missing", observation_indices=indices
        )
    observation = ocr.observations[indices[0]]
    token = (observation.text or "").strip()
    if len(token) > 128 or not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", token):
        return NumericObservation(
            status="unsupported", observation_indices=indices, confidence=observation.confidence
        )
    return NumericObservation(
        status="parsed",
        token=token,
        value=token,
        observation_indices=indices,
        confidence=observation.confidence,
    )


def _tracks(result):
    previous = None
    for point in result.points:
        if point.status != "complete":
            previous = None
            continue
        if result.request.track_numbers:
            point.number = _number(point.ocr)
        frame = point.ocr.preparation.frame
        later = previous and Fraction(frame.time_base) * frame.original_pts > (
            Fraction(previous.ocr.preparation.frame.time_base)
            * previous.ocr.preparation.frame.original_pts
        )
        if later:
            if point.ocr.text and previous.ocr.text:
                point.text_changed = point.ocr.text != previous.ocr.text
            if (
                point.number
                and previous.number
                and point.number.status == previous.number.status == "parsed"
                and Decimal(point.number.value) < Decimal(previous.number.value)
            ):
                result.numeric_candidates.append(
                    NumericReversal(
                        previous_point_index=previous.index,
                        point_index=point.index,
                        actual_seconds=frame.actual_seconds,
                        previous_value=previous.number.value,
                        value=point.number.value,
                        previous_confidence=previous.number.confidence,
                        confidence=point.number.confidence,
                        source_sha256=result.request.expected_source_sha256,
                        previous_raw_backend_sha256=previous.ocr.raw_backend_artifact["sha256"],
                        raw_backend_sha256=point.ocr.raw_backend_artifact["sha256"],
                    )
                )
        previous = point


def _append_artifacts(result, records):
    existing = {record["path"]: record for record in result.artifacts}
    for record in records:
        if record["path"] in existing and existing[record["path"]] != record:
            raise ValueError("Timeline artifact has conflicting file commitments")
        existing[record["path"]] = record
    size = sum(record["bytes"] for record in existing.values())
    if size > MAX_ARTIFACT_BYTES:
        raise ValueError("Timeline artifacts exceed the 8 MiB aggregate budget")
    result.artifacts = list(existing.values())
    result.artifact_bytes = size


async def _speech(result):
    from .transcript import read_transcript
    from .transcript_formats import artifact_record

    request = result.request.transcript
    if request is None:
        return
    try:
        data = await read_transcript(
            request.output_directory,
            request.expected_receipt_sha256,
            file_path=request.file_path,
            expected_source_sha256=request.expected_source_sha256,
        )
        directory = Path(data["receipt"]["directory"])
        records = [*data["artifacts"], data["receipt"]]
        records.append(
            artifact_record(
                directory, directory / "transcript-result.json", "complete_result_state"
            )
        )
        records = [{**r, "path": str(directory / r["path"])} for r in records]
        _append_artifacts(result, records)
        result.speech = TimelineSpeech(status="verified_readback", transcript=data)
    except Exception as exc:
        result.speech = TimelineSpeech(status="failed", error=_error(exc))


def _reservation(request):
    # The existing frame renderer reserves RGBA PNG bytes plus 64 KiB encoder overhead.
    return 4 * request.max_pixels + 65536 + MAX_RAW_BYTES + 2 * MAX_MANIFEST_BYTES


def _clock(ocr, request, seconds):
    frame, source = ocr.preparation.frame, ocr.source
    if source["sha256"] != request.expected_source_sha256 or checked_path(
        source["path"]
    ) != checked_path(request.file_path):
        raise ValueError("OCR source differs from the timeline source")
    if frame.requested_seconds != seconds:
        raise ValueError("OCR preparation clock differs from its requested source point")


async def _verify_artifacts(records):
    from .transcript_formats import _empty_artifact

    for record in records:
        path = checked_path(record["path"])
        actual = _empty_artifact(path) if record["bytes"] == 0 else await copy_hash(path)
        if actual != (record["sha256"], record["bytes"]):
            raise ValueError("Timeline artifact identity changed before promotion")


async def _point(request, point, remaining):
    data = await recognize_image(
        ImageOCRRequest(
            **request.model_dump(exclude={"times_seconds", "track_numbers", "transcript"}),
            time_seconds=point.requested_seconds,
        )
    )
    try:
        ocr = TimelineOCR.model_validate(data)
        _clock(ocr, request, point.requested_seconds)
        records = [*ocr.artifacts, ocr.manifest, ocr.preparation.manifest.model_dump(mode="json")]
        if sum(record["bytes"] for record in records) > min(remaining, _reservation(request)):
            raise ValueError("OCR artifacts exceed the reserved timeline byte budget")
        await _verify_artifacts(records)
        return ocr, records
    except BaseException:
        try:
            _discard_views(
                [data], Path(get_config().cache_dir).expanduser().resolve() / "media" / "views"
            )
        except Exception as cleanup_error:
            point.cleanup_error = _error(cleanup_error)
        raise


async def _collect(result):
    stop = None
    for point in result.points:
        remaining = MAX_ARTIFACT_BYTES - result.artifact_bytes
        if stop or remaining < _reservation(result.request):
            point.reason = stop or "artifact_budget"
            continue
        point.reason = "in_progress"
        try:
            ocr, records = await _point(result.request, point, remaining)
            _append_artifacts(result, records)
            point.ocr, point.status, point.reason = ocr, "complete", None
        except Exception as exc:
            point.status, point.reason, point.error = "failed", "point_failed", _error(exc)
            if isinstance(exc, ImportError):
                stop = "backend_unavailable"
            elif isinstance(exc, TimeoutError):
                stop = "deadline"


def _interrupted(result, exc):
    result.error = _error(exc)
    reason = "deadline" if isinstance(exc, TimeoutError) else "source_or_readback_failure"
    for point in result.points:
        if point.reason == "in_progress":
            point.status, point.error = "failed", result.error
        if point.status != "complete":
            point.reason = reason
    if result.request.transcript and (
        result.speech.status == "not_run"
        or result.speech.status == "verified_readback"
        and reason != "deadline"
    ):
        result.speech.status, result.speech.error = "failed", result.error


def _finish(result):
    complete = [point for point in result.points if point.status == "complete"]
    speech_complete = result.speech.status == "absent" or (
        result.speech.status == "verified_readback"
        and result.speech.transcript.status == "complete"
    )
    all_complete = len(complete) == len(result.points) and speech_complete
    has_evidence = bool(complete) or result.speech.status == "verified_readback"
    result.status = "partial" if has_evidence else "failed"
    if all_complete and result.source_verified:
        result.status = "complete"
    elif result.error and not result.source_verified and result.error.category != "NETWORK_ERROR":
        result.status = "failed"
    coverage_complete = len(complete) == len(result.points) and result.source_verified
    result.coverage = NativeCoverage(
        sampled_points=[point.ocr.preparation.frame.actual_seconds for point in complete],
        decoded_count=len(complete),
        requested_window=None,
        complete=coverage_complete,
        stop_reason=None if coverage_complete else "requested_points_incomplete_or_unverified",
        watched_intervals=[],
    )
    _tracks(result)
    return result.model_dump(mode="json")


async def build_ocr_timeline(request: TemporalOCRRequest) -> dict:
    """Observe selected local frames and read existing speech without new inference.

    Args:
        request: One exact source, ordered points, local OCR and optional receipt readback.

    Returns:
        Typed point records, retained failures and distinct speech/numeric channels.
    """
    request = TemporalOCRRequest.model_validate(
        request.model_dump(mode="json") if isinstance(request, TemporalOCRRequest) else request
    )
    result = TemporalOCRResult(
        request=request,
        points=[
            OCRTimelinePoint(index=i, requested_seconds=t)
            for i, t in enumerate(request.times_seconds)
        ],
        speech=TimelineSpeech(status="not_run" if request.transcript else "absent"),
    )
    try:
        async with asyncio.timeout(DEADLINE_SECONDS):
            path = checked_path(request.file_path)
            digest, size = await copy_hash(path)
            if digest != request.expected_source_sha256:
                raise ValueError("Source SHA256 differs from the timeline source")
            result.source = {"path": str(path), "sha256": digest, "bytes": size}
            await _speech(result)
            await _collect(result)
            await _verify_artifacts(result.artifacts)
            if result.speech.status == "verified_readback":
                from .transcript import read_transcript

                speech = request.transcript
                await read_transcript(
                    speech.output_directory,
                    speech.expected_receipt_sha256,
                    file_path=speech.file_path,
                    expected_source_sha256=speech.expected_source_sha256,
                )
            if await copy_hash(path) != (digest, size):
                raise ValueError("Source changed during the OCR timeline")
            result.source_verified = True
    except Exception as exc:
        _interrupted(result, exc)
    return _finish(result)
