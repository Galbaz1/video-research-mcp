"""One-deadline local tutorial artifacts with PDF as the final atomic commit point."""

import asyncio
import os
import shutil
import tempfile
import time
from pathlib import Path

from pydantic import ValidationError

from ..config import get_config
from ..errors import make_tool_error
from ..image_preprocessing import image_worker
from ..models.video_note import VideoNoteRequest, VideoNoteResult
from .frames import collect_frames
from .io import (MAX_FRAME_BYTES, MAX_PAGE_BYTES, MAX_PAGES, MAX_PDF_BYTES, MAX_STAGE_BYTES,
                 MAX_TOTAL_PAGE_PIXELS, NoteError, admit, canonical, digest, read_bytes, source_record,
                 verify_destination, write_bytes)
from .perception import plan_steps, supplied_plan
from .render import dependencies_ready, render_verified


def _check(deadline):
    if time.monotonic() >= deadline or asyncio.current_task().cancelling():
        raise TimeoutError("Tutorial operation canceled or exceeded its overall deadline")


def _limits(timeout):
    return {"max_steps": 16, "max_pages": MAX_PAGES, "max_pdf_bytes": MAX_PDF_BYTES,
            "max_frame_bytes": MAX_FRAME_BYTES, "max_frame_pixels": 250000,
            "max_raster_bytes": MAX_PAGE_BYTES, "max_raster_pixels": MAX_TOTAL_PAGE_PIXELS,
            "max_retained_bytes": MAX_STAGE_BYTES, "max_artifacts": 64,
            "operation_timeout_seconds": timeout, "font": "base14_Helvetica_WinAnsi",
            "native_deadline": "cooperative joined worker; checks between bounded page operations"}


def _provenance():
    return {"factual_correctness_verified": False, "human_review": "pending",
            "final_model_review": "unperformed", "continuous_watched_coverage": False,
            "config_bootstrap_environment_nonmutation_verified": False,
            "illustrations": "temporal_source_points; semantic_relevance_unreviewed"}


def _base(request, source, steps, perception, timeout):
    return {"status": "dry_run", "source": source, "supplied_steps": request.steps,
            "steps": steps, "output_path": request.output_path, "perception": perception,
            "verification": {"source_hash": "pass", "step_structure": "pass",
                             "source_extent": "unverified", "pdf_structure": "unperformed",
                             "page_text_decode": "unperformed", "all_pages_rasterized": "unperformed"},
            "provenance": _provenance(), "limits": _limits(timeout)}


def _extent(request, steps, observed):
    if observed is not None and any(step["end_seconds"] > observed for step in
                                    [*steps, *(step.model_dump() for step in request.steps)]):
        raise NoteError("Tutorial interval exceeds the observed original source extent")


def _verify_artifacts(directory, records, deadline):
    if len(records) > 64 or sum(item["bytes"] for item in records) > MAX_STAGE_BYTES:
        raise NoteError("Tutorial retained artifacts exceed their count/byte bound")
    for record in records:
        _check(deadline)
        path = Path(record["path"])
        if path.parent != directory or digest(read_bytes(path, record["bytes"])) != record["sha256"]:
            raise NoteError("Tutorial artifact changed or escaped its owned directory")
    _check(deadline)


def _verify_frames(directory, frames, buffers, deadline):
    _verify_artifacts(directory, frames, deadline)
    if len(frames) != len(buffers) or any(digest(data) != frame["sha256"] for frame, data in
                                         zip(frames, buffers, strict=True)):
        raise NoteError("Tutorial embedded frame buffer differs from its retained PNG")


def _manifest(request, source, steps, frames, perception, warnings, directory):
    document = {"schema_version": 1, "title": request.title, "source": source,
                "supplied_steps": [step.model_dump(mode="json") for step in request.steps],
                "steps": steps, "frames": frames, "perception": perception, "warnings": warnings,
                "coverage": {"sampled_points": [frame["actual_seconds"] for frame in frames],
                             "watched_intervals": []}, "provenance": _provenance()}
    data = canonical(document)
    if len(data) > 256 * 1024:
        raise NoteError("Tutorial manifest exceeds 256 KiB")
    manifest = write_bytes(directory / "manifest.json", data)
    return {**document, "manifest_sha256": manifest["sha256"]}, manifest


async def _build(request, admitted, source, deadline, timeout, directory):
    steps, perception, warnings = await plan_steps(request, source)
    _extent(request, steps, perception["source_extent_seconds"])
    _check(deadline)
    frames, buffers, frame_warnings, observed = await collect_frames(source, steps, directory)
    warnings.extend(frame_warnings)
    _extent(request, steps, observed)
    if observed is None and perception["source_extent_seconds"] is None:
        warnings.append("Original duration/clock not observed; supplied step intervals remain unverified.")
    _verify_frames(directory, frames, buffers, deadline)
    document, manifest = _manifest(request, source, steps, frames, perception, warnings, directory)
    pdf, pages, layout = await image_worker(render_verified, document, frames, buffers, directory, deadline=deadline)
    _check(deadline)
    _verify_frames(directory, frames, buffers, deadline)
    _verify_artifacts(directory, [pdf, manifest, layout, *frames, *pages], deadline)
    receipt = write_bytes(directory / "receipt.json", canonical({
        "schema_version": 1, "pdf": {**pdf, "path": str(admitted[1])}, "manifest": manifest,
        "pages": pages, "frames": frames, "layout": layout, "checks": {"pdf_structure": "pass",
        "page_text_decode": "pass", "all_pages_rasterized": "pass"}, "provenance": _provenance()}))
    result = _base(request, source, steps, perception, timeout)
    result.update(status="complete", output_path=str(admitted[1]), artifact_directory=str(directory),
                  pdf={**pdf, "path": str(admitted[1])}, manifest=manifest, receipt=receipt,
                  page_count=len(pages), frames=frames, warnings=warnings)
    result["verification"].update(source_extent="pass" if observed is not None or perception["source_extent_seconds"] is not None else "unverified",
                                  pdf_structure="pass", page_text_decode="pass", all_pages_rasterized="pass")
    result = VideoNoteResult.model_validate(result).model_dump(mode="json")
    await source_record(admitted[0], source["sha256"], admitted[2])
    _check(deadline)
    _verify_frames(directory, frames, buffers, deadline)
    _verify_artifacts(directory, [pdf, manifest, receipt, layout, *frames, *pages], deadline)
    verify_destination(admitted[1], admitted[3], admitted[4])
    _check(deadline)
    if admitted[3] is None:
        try:
            os.link(pdf["path"], admitted[1], follow_symlinks=False)
        except FileExistsError as error:
            raise NoteError("Tutorial destination was created before publication") from error
        Path(pdf["path"]).unlink()
    else:
        os.replace(pdf["path"], admitted[1])
    return result


async def _workflow(request):
    timeout = get_config().media_acquire_timeout_seconds
    directory, committed = None, False
    try:
        async with asyncio.timeout(timeout):
            deadline = time.monotonic() + timeout
            admitted = admit(request)
            source = await source_record(admitted[0], request.expected_source_sha256, admitted[2])
            if request.dry_run:
                report = {"status": "deferred" if request.perception else "not_requested", "windows": [],
                          "abstentions": [], "counts": {}, "timeline": [], "source_extent_seconds": None,
                          "factual_correctness_verified": False}
                return VideoNoteResult.model_validate(_base(request, source, supplied_plan(request), report, timeout)).model_dump(mode="json")
            dependencies_ready()
            _check(deadline)
            verify_destination(admitted[1], admitted[3], admitted[4])
            directory = Path(tempfile.mkdtemp(prefix=admitted[1].stem + "-note-", dir=admitted[1].parent))
            owned_identity = directory.stat().st_dev, directory.stat().st_ino
            os.chmod(directory, 0o700)
            result = await _build(request, admitted, source, deadline, timeout, directory)
            committed = True
            return result
    finally:
        if directory is not None and not committed and directory.exists() and not directory.is_symlink():
            current = directory.stat()
            if (current.st_dev, current.st_ino) == owned_identity:
                shutil.rmtree(directory)


async def create_note(request):
    """Return a pure dry plan or retained PDF artifacts without exposing raw diagnostics."""
    try:
        return await _workflow(VideoNoteRequest.model_validate(request))
    except Exception as error:
        if isinstance(error, ImportError):
            value = make_tool_error(ImportError("Tutorial dependencies missing or incompatible; install video-research-mcp[tutorial]"))
            value["category"] = "DEPENDENCY_MISSING"
        elif isinstance(error, NoteError):
            value = make_tool_error(error)
            value["category"] = "SCHEMA_VALIDATION_FAILED"
        elif isinstance(error, ValidationError):
            message = error.errors(include_input=False, include_context=False)[0]["msg"]
            value = make_tool_error(ValueError("Tutorial request rejected: " + message))
            value["category"] = "SCHEMA_VALIDATION_FAILED"
        else:
            value = make_tool_error(TimeoutError("Tutorial overall deadline exceeded; owned worker joined")
                                    if isinstance(error, TimeoutError) else
                                    ValueError("Tutorial note failed; raw diagnostic withheld"))
        value.update(operation="video_note_create", retryable=False, provenance=_provenance())
        return value
