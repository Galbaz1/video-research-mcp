"""Bounded offline evidence exports; no provider, browser, decoder or shadow database."""

import base64
from contextlib import contextmanager
import hashlib
import json
import os

from .collections_owned_io import open_owned, verify_output, verify_root
from .evidence_export_html import bounded, html_parts, markdown_parts
from .evidence_export_records import select
from .media_local_io import _open_regular
from .media_snapshot import checked_path
from .models.evidence_export import Response


def frame_bytes(ref, remaining: int) -> tuple[bytes, str]:
    """Read at most 256 KiB through the existing regular-file and path fences."""
    path = checked_path(ref["path"])
    with _open_regular(path) as reader:
        before = os.fstat(reader.fileno())
        if not 0 < before.st_size <= min(262144, remaining):
            raise ValueError("Frame exceeds per-frame or max_inline_bytes bound")
        raw = reader.read(before.st_size + 1)
        after, current = os.fstat(reader.fileno()), path.lstat()
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if len(raw) != before.st_size or any(getattr(before, k) != getattr(after, k) or getattr(before, k) != getattr(current, k) for k in fields):
            raise ValueError("Frame changed during bounded read")
    if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError("Frame digest differs from canonical/supplied reference")
    mime = "image/png" if raw.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if raw.startswith(b"\xff\xd8\xff") else "image/webp" if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP" else None
    if mime is None:
        raise ValueError("Frame format must be PNG, JPEG or WebP; no SVG/HTML")
    return raw, mime


def illustrate(records, request) -> tuple[list, dict, list]:
    """Name every missing/refused frame; never emit an image for a failed reference."""
    output, inline, issues, cache, used = [], {}, [], {}, 0
    for record in records:
        value = record.model_dump(mode="json")
        value["frames"] = []
        for ref in value["artifact_refs"]:
            if ref["kind"] != "frame":
                continue
            key = hashlib.sha256(json.dumps(ref, sort_keys=True).encode()).hexdigest()
            if key not in cache:
                try:
                    raw, mime = frame_bytes(ref, request.max_inline_bytes - used)
                    used += len(raw)
                    inline[key] = f'data:{mime};base64,' + base64.b64encode(raw).decode("ascii")
                    cache[key] = {**ref, "key": key, "state": "inline_verified", "bytes": len(raw), "mime": mime}
                except (OSError, ValueError) as error:
                    state = "missing" if isinstance(error, FileNotFoundError) else "refused"
                    cache[key] = {**ref, "state": state, "reason": str(error)[:512]}
                    if request.missing_frames == "refuse":
                        raise ValueError(f'Frame {ref["artifact_id"]} {state}: {error}') from error
            frame = cache[key]
            value["frames"].append(frame)
            if frame["state"] != "inline_verified":
                issues.append({"citation_id": value["citation_id"], **frame})
        output.append(value)
    return output, inline, issues


@contextmanager
def hold_parent(directory):
    """Retain the admitted parent across asynchronous evidence selection."""
    parent = checked_path(str(directory.parent))
    before = parent.stat()
    fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        current, opened = checked_path(str(parent)).stat(), os.fstat(fd)
        if any((value.st_dev, value.st_ino) != (opened.st_dev, opened.st_ino) for value in (before, current)):
            raise PermissionError("Export parent changed before selection")
        yield fd
    finally:
        os.close(fd)


def publish(directory, files, parent_fd) -> list[dict]:
    """Create exclusive fenced outputs; clean only files owned through the held directory."""
    current, opened = checked_path(str(directory.parent)).stat(), os.fstat(parent_fd)
    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
        raise PermissionError("Export parent changed during selection")
    os.mkdir(directory.name, mode=0o700, dir_fd=parent_fd)
    fd, directory_identity, created, artifacts = None, None, [], []
    try:
        directory_identity = os.stat(directory.name, dir_fd=parent_fd, follow_symlinks=False)
        fd = open_owned(directory)
        for name, raw in files.items():
            verify_root(directory, fd)
            handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            created.append(name)
            with os.fdopen(handle, "wb") as writer:
                writer.write(raw)
                writer.flush()
                os.fsync(writer.fileno())
                identity = os.fstat(writer.fileno())
            target = directory / name
            verify_output(target, fd, identity)
            with _open_regular(target) as reader:
                if os.fstat(reader.fileno()).st_size != len(raw) or reader.read(len(raw) + 1) != raw:
                    raise ValueError("Export artifact readback differs")
            verify_output(target, fd, identity)
            artifacts.append({"path": str(target), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        os.fsync(fd)
        return artifacts
    except BaseException as primary:
        try:
            if directory_identity is None:
                raise OSError("Created export directory identity is unknown")
            for name in created:
                os.unlink(name, dir_fd=fd)
            current = os.stat(directory.name, dir_fd=parent_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (directory_identity.st_dev, directory_identity.st_ino):
                raise PermissionError("Export directory changed before cleanup")
            os.rmdir(directory.name, dir_fd=parent_fd)
        except OSError as cleanup:
            raise OSError(f"Export failed: {primary}; cleanup incomplete at {directory}: {cleanup}") from primary
        raise
    finally:
        if fd is not None:
            os.close(fd)


async def export(request) -> dict:
    """Select canonical evidence and publish an admitted local review bundle."""
    directory = checked_path(request.output_directory)
    if directory.exists() or not directory.parent.is_dir():
        raise FileExistsError("Export requires an absent directory beneath an existing parent")
    with hold_parent(directory) as parent_fd:
        return await export_selected(request, directory, parent_fd)


async def export_selected(request, directory, parent_fd) -> dict:
    """Prepare the bounded report while its output parent remains held."""
    records, selection = await select(request.source)
    if len(records) > 50:
        raise ValueError("Export exceeds 50 records")
    # Refuse oversized metadata before opening any evidence frame.
    bounded([json.dumps([r.model_dump(mode="json") for r in records], ensure_ascii=False)], request.max_export_bytes)
    values, inline, issues = illustrate(records, request)
    report = {"schema": "offline_evidence_v1", "title": request.title, "selection": selection, "records": values,
              "complete": not issues, "frame_issues": issues, "provider_calls": 0,
              "evidence_verification": "inline_frame_bytes_verified_only; semantic_and_caller_claims_unqualified"}
    files = {}
    for format_name in request.formats:
        remaining = request.max_export_bytes - sum(map(len, files.values()))
        if format_name == "html":
            files["report.html"] = bounded(html_parts(report, inline), remaining)
        elif format_name == "markdown":
            files["report.md"] = bounded(markdown_parts(report), remaining)
        else:
            files["report.json"] = bounded([json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False)], remaining)
    artifacts = publish(directory, files, parent_fd)
    return Response(status="partial" if issues else "exported" if records else "no_evidence", complete=not issues,
                    output_directory=str(directory), records=len(records), artifacts=artifacts,
                    frame_issues=issues, selection=selection).model_dump(mode="json")
