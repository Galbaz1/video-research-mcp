"""Bounded one-image local OCR and exact prepared/oriented/stored-pixel provenance."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import math
import shutil
import time
import unicodedata
from pathlib import Path

from .config import get_config
from .image_vision import MAX_RAW_BYTES, _read, remaining, run_vision
from .media_process import run_media_process
from .media_snapshot import checked_path, copy_hash, view_directory
from .models.image_edit import ImageEditRequest
from .models.image_ocr import ImageOCRRequest, ImageOCRResult, OCRObservation
from .native_media_results import _discard_views

MAX_OBSERVATIONS = 128
MAX_TEXT_BYTES = 64 * 1024


def _points(box):
    x, y, width, height = box
    return [[x, y], [x + width, y], [x + width, y + height], [x, y + height]]


def _cjk(character):
    """Identify adjacent CJK glyphs whose OCR word join does not require a space."""
    return any(lo <= ord(character) <= hi for lo, hi in (
        (0x3040, 0x30FF), (0x3400, 0x9FFF), (0xAC00, 0xD7AF), (0x20000, 0x3134F)
    ))


def _joined(words):
    """Preserve raw word strings while joining adjacent CJK glyphs deterministically."""
    result = words[0] if words else ""
    for word in words[1:]:
        result += ("" if _cjk(result[-1]) and _cjk(word[0]) else " ") + word
    return result


def parse_tsv(raw: bytes) -> list[dict]:
    """Parse bounded Tesseract words and derived lines without discarding malformed rows."""
    if len(raw) > MAX_RAW_BYTES:
        raise ValueError("OCR raw payload exceeds 256 KiB")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")), delimiter="\t")
    required = {"level", "page_num", "block_num", "par_num", "line_num", "word_num",
                "left", "top", "width", "height", "conf", "text"}
    if set(reader.fieldnames or []) != required:
        raise ValueError("Tesseract returned an unsupported TSV header")
    words, groups = [], {}
    for index, row in enumerate(reader):
        if index >= 512 or None in row or any(value is None for value in row.values()):
            raise ValueError("Tesseract TSV row count or shape exceeds the protocol")
        level = int(row["level"])
        if not 1 <= level <= 5:
            raise ValueError("Tesseract returned an unsupported TSV level")
        if level != 5 or not row["text"].strip():
            continue
        box = [int(row[key]) for key in ("left", "top", "width", "height")]
        confidence = float(row["conf"])
        if not math.isfinite(confidence) or not -1 <= confidence <= 100:
            raise ValueError("Tesseract returned an invalid confidence")
        line_id = [int(row[key]) for key in ("page_num", "block_num", "par_num", "line_num")]
        value = {"kind": "word", "text": row["text"], "raw_box": box,
                 "raw_points": _points(box), "confidence": confidence / 100 if confidence >= 0 else None,
                 "line_id": line_id}
        words.append(value)
        groups.setdefault(tuple(line_id), []).append(value)
    lines = []
    for values in groups.values():
        left = min(value["raw_box"][0] for value in values)
        top = min(value["raw_box"][1] for value in values)
        right = max(value["raw_box"][0] + value["raw_box"][2] for value in values)
        bottom = max(value["raw_box"][1] + value["raw_box"][3] for value in values)
        box = [left, top, right - left, bottom - top]
        lines.append({"kind": "line", "text": _joined([v["text"] for v in values]),
                      "raw_box": box, "raw_points": _points(box), "confidence": None,
                      "line_id": values[0]["line_id"]})
    return _bounded([*words, *lines])


def _bounded(values):
    """Reject overfull observation/text denominators rather than silently truncate them."""
    if len(values) > MAX_OBSERVATIONS or sum(
        len((value.get("text") or value.get("payload") or "").encode()) for value in values
    ) > MAX_TEXT_BYTES:
        raise ValueError("OCR observations exceed 128 entries or 64 KiB aggregate text")
    return values


def _map(matrix, point):
    x, y = point
    denominator = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2]
    if not denominator:
        raise ValueError("OCR pixel transform is singular")
    return [(matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]) / denominator,
            (matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]) / denominator]


def map_observation(value: dict, preparation: dict, *, native: bool) -> dict:
    """Keep backend geometry and map pixel corners into oriented and stored original grids."""
    from .image_preprocessing import inverse

    artifact, transforms = preparation["artifact"], preparation["transforms"]
    width, height = artifact["width"], artifact["height"]
    box = value["raw_box"]
    if len(box) != 4 or any(type(v) not in {int, float} or not math.isfinite(v) for v in box):
        raise ValueError("OCR boxes require four finite backend coordinates")
    if min(box[:2]) < 0 or min(box[2:]) <= 0 or (
        box[0] + box[2] > (1 if native else width)
        or box[1] + box[3] > (1 if native else height)
    ):
        raise ValueError("OCR box is outside the prepared image")
    raw_points = value["raw_points"]
    if len(raw_points) != 4 or any(len(point) != 2 for point in raw_points):
        raise ValueError("OCR quadrilaterals must contain four two-dimensional points")
    if any(type(v) not in {int, float} or not math.isfinite(v) for point in raw_points for v in point):
        raise ValueError("OCR points require finite backend coordinates")
    if value.get("kind") in {"line", "word"} and not isinstance(value.get("text"), str):
        raise ValueError("Text observations require exact backend text")
    if native:
        if any(not 0 <= coordinate <= 1 for point in raw_points for coordinate in point):
            raise ValueError("Vision normalized geometry is outside the prepared image")
        points = [[x * width, (1 - y) * height] for x, y in raw_points]
    else:
        points = raw_points
    if any(not 0 <= x <= width or not 0 <= y <= height for x, y in points):
        raise ValueError("OCR geometry is outside the prepared image")
    mapped = {**value, "coordinate_space": "normalized_bottom_left" if native else "prepared_top_left_pixels",
              "prepared_points": points,
              "oriented_points": [_map(inverse(transforms["oriented_to_output"]), p) for p in points],
              "stored_points": [_map(transforms["output_to_source"], p) for p in points]}
    return OCRObservation.model_validate(mapped).model_dump(mode="json")


def locate_text(observations, query: str | None, limit: int) -> tuple[list[dict], int]:
    """Locate lexical substrings in joined lines; returned geometry covers the whole line."""
    if query is None:
        return [], 0
    needle = unicodedata.normalize("NFKC", query).casefold()
    matches, total = [], 0
    for index, value in enumerate(observations):
        if value["kind"] != "line":
            continue
        haystack = unicodedata.normalize("NFKC", value["text"]).casefold()
        occurrences = haystack.count(needle)
        total += occurrences
        for occurrence in range(min(occurrences, limit - len(matches))):
            matches.append({"observation_index": index, "occurrence": occurrence,
                            "query": query, "method": "casefold_nfkc_substring_on_joined_lines",
                            "geometry_scope": "whole_line_observation"})
    return matches, total


async def _tesseract(image: Path, request: ImageOCRRequest, deadline: float):
    executable = shutil.which("tesseract")
    if executable is None:
        raise ImportError("Local OCR requires optional installed Tesseract; no model fallback is used")
    command = [executable, str(image), "stdout", "--psm", "6"]
    if request.languages:
        command += ["-l", "+".join(request.languages)]
    raw, _ = await run_media_process([*command, "tsv"], remaining(deadline))
    return raw, parse_tsv(raw), {"engine": "tesseract", "invocations": 1,
                               "version": "unverified", "language_data": "runtime_selected_unverified"}


async def _finish(preparation, request, raw, observations, runtime, directory):
    """Retain exact raw bytes and write a separate final OCR manifest with actual artifact readback."""
    from .image_manifest import write_manifest

    suffix = "json" if request.engine == "vision" else "tsv"
    raw_path = directory / ("ocr-raw." + suffix)
    with raw_path.open("xb") as stream:
        stream.write(raw)
    raw_path.chmod(0o600)
    digest, size = await copy_hash(raw_path)
    raw_artifact = {"path": str(raw_path), "sha256": digest, "bytes": size,
                    "mime": "application/json" if suffix == "json" else "text/tab-separated-values"}
    matches, total = locate_text(observations, request.locate, request.max_matches)
    data = {"status": "complete", "engine": request.engine, "preparation": preparation,
            "source": preparation["source"], "artifacts": [*preparation["artifacts"], raw_artifact],
            "raw_backend_artifact": raw_artifact, "observations": observations,
            "text": "\n".join(v["text"] for v in observations if v["kind"] == "line"),
            "matches": matches, "match_count": total, "matches_truncated": total > len(matches),
            "runtime": runtime, "limits": {"max_images": 1, "max_observations": MAX_OBSERVATIONS,
            "max_raw_bytes": MAX_RAW_BYTES, "max_text_bytes": MAX_TEXT_BYTES,
            "max_artifacts_bytes": 8 * 1024 * 1024, "max_manifest_bytes": 128 * 1024},
            "provenance": {"method": "local_source_observations", "semantic_table_structure": "unknown",
            "source_revision": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "request": request.model_dump(mode="json"), "cloud_calls": 0}}
    data["manifest"] = await write_manifest(data, directory)
    return ImageOCRResult.model_validate(data).model_dump(mode="json")


async def recognize_image(request: ImageOCRRequest) -> dict:
    """Recognize one source-derived PNG locally, preserving exact original and inverse geometry."""
    from .image_edit import edit_image

    request = ImageOCRRequest.model_validate(request)
    if request.engine == "tesseract" and shutil.which("tesseract") is None:
        raise ImportError("Local OCR requires optional installed Tesseract; no model fallback is used")
    directory = view_directory()
    preparation = None
    deadline = time.monotonic() + get_config().media_acquire_timeout_seconds
    try:
        async with asyncio.timeout(remaining(deadline)):
            preparation = await edit_image(ImageEditRequest(
                **request.model_dump(include={
                    "file_path", "expected_source_sha256", "time_seconds", "max_pixels"
                }), crop=request.crop, resize=request.resize,
            ))
            image = directory / "prepared.png"
            artifact = preparation["artifact"]
            image_bytes = _read(checked_path(artifact["path"]), 8 * 1024 * 1024)
            if (hashlib.sha256(image_bytes).hexdigest(), len(image_bytes)) != (artifact["sha256"], artifact["bytes"]):
                raise ValueError("Prepared OCR image differs from its source-derived artifact")
            with image.open("xb") as stream:
                stream.write(image_bytes)
            image.chmod(0o600)
            if request.engine == "vision":
                raw, payload, runtime = await run_vision(image, {
                    "languages": request.languages, "barcodes": request.detect_barcodes,
                    "documents": request.detect_document_bounds,
                }, directory, deadline)
                if (payload["width"], payload["height"]) != (artifact["width"], artifact["height"]):
                    raise ValueError("Vision protocol dimensions differ from the prepared artifact")
                values = _bounded(payload["observations"])
            else:
                raw, values, runtime = await _tesseract(image, request, deadline)
            observations = [map_observation(value, preparation, native=request.engine == "vision") for value in values]
            image.unlink()
            return await _finish(preparation, request, raw, observations, runtime, directory)
    except BaseException:
        shutil.rmtree(directory)
        if preparation is not None:
            _discard_views([preparation], directory.parent)
        raise
