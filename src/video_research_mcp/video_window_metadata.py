"""Normalize requested local-video windows to canonical SDK duration values."""

from __future__ import annotations

from decimal import Decimal
import math
import re

from google.genai import types

_DURATION = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d{1,3})?)s)?")


def _milliseconds(value: str) -> int:
    """Parse ordered hour/minute/second units with millisecond precision."""
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise ValueError("Offsets must be duration strings of at most 64 characters")
    match = _DURATION.fullmatch(value)
    if match is None or not any(match.groups()):
        raise ValueError("Offsets require ordered h/m/s units, for example '27m' or '1m30.5s'")
    hours, minutes, seconds = match.groups()
    total = Decimal(hours or 0) * 3600 + Decimal(minutes or 0) * 60 + Decimal(seconds or 0)
    milliseconds = int(total * 1000)
    if milliseconds > 2**53 - 1:
        raise ValueError("Offset exceeds the supported millisecond range")
    return milliseconds


def _duration(milliseconds: int) -> str:
    """Encode the normalized time without floating-point rounding."""
    return f"{milliseconds // 1000}.{milliseconds % 1000:03d}s"


def normalize_window(
    fps: float | None, start_offset: str | None, end_offset: str | None
) -> types.VideoMetadata | None:
    """Validate user input and return one canonical static sampling request."""
    if all(value is None for value in (fps, start_offset, end_offset)):
        return None
    if fps is not None and (
        type(fps) not in (float, int) or not math.isfinite(fps) or not 0 < fps <= 30
    ):
        raise ValueError("fps must be a finite number greater than zero and at most 30")
    start_ms = _milliseconds(start_offset) if start_offset is not None else 0
    end_ms = _milliseconds(end_offset) if end_offset is not None else None
    if end_ms is not None and end_ms <= start_ms:
        raise ValueError("end_offset must be greater than start_offset")
    return types.VideoMetadata(
        fps=float(fps) if fps is not None else None,
        start_offset=_duration(start_ms),
        end_offset=_duration(end_ms) if end_ms is not None else None,
    )


def window_description(metadata: types.VideoMetadata) -> dict:
    """Describe requested provider positions without claiming observed coverage."""
    return {
        **metadata.model_dump(mode="json", exclude_none=True),
        "media_processing": "STATIC",
        "timestamp_origin": "original source presentation timeline",
        "observed_coverage": "unknown",
        "watched_intervals": [],
    }


def window_instruction(instruction: str, metadata: types.VideoMetadata | None) -> str:
    """Keep model-reported timestamps relative to the original source window."""
    if metadata is None:
        return instruction
    end = metadata.end_offset or "the end of the source"
    return (
        f"{instruction}\n\nRequested source interval: {metadata.start_offset} to {end}. "
        "Report timestamps on the original source presentation timeline; do not reset "
        "the window start to zero. Sampling does not establish complete observed coverage."
    )
