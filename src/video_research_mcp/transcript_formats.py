"""Atomic bounded transcript exports and externally committed exact-byte restart readback."""

import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path

from .media_snapshot import checked_path, copy_hash
from .media_local_io import _open_regular
from .transcript_captions import strict_json
from .vision_preparation import read_payload

MAX_RESULT_BYTES = 4 * 1024 * 1024


def encoded(value) -> bytes:
    """Serialize finite canonical JSON with a fixed complete-result ceiling."""
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if len(data) > MAX_RESULT_BYTES:
        raise ValueError("Transcript JSON exceeds4MiB; complete results cannot be truncated")
    return data


def write_artifact(directory: Path, name: str, data: bytes, role: str) -> dict:
    """Promote only a fresh owned filename after fsync; never overwrite an existing artifact."""
    if Path(name).name != name or not name or len(data) > 8 * 1024 * 1024:
        raise ValueError("Transcript artifact name/bytes exceed the fixed contract")
    target, temporary = directory / name, directory / ("." + name + ".pending")
    checked_path(str(directory))
    if target.exists() or target.is_symlink():
        raise FileExistsError("Transcript artifacts cannot overwrite an existing file")
    with temporary.open("xb") as stream:
        temporary.chmod(0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, target)
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "role": role}


def _milliseconds(seconds: float) -> int:
    return math.floor(seconds * 1000 + 0.5)


def _clock(milliseconds: int, separator: str) -> str:
    hour, rest = divmod(milliseconds, 3600000)
    minute, rest = divmod(rest, 60000)
    second, millis = divmod(rest, 1000)
    return f"{hour:02d}:{minute:02d}:{second:02d}{separator}{millis:03d}"


def export_bytes(kind: str, segments: list, provenance: dict, untimed: list) -> tuple[bytes, dict]:
    """Preserve full JSON or explicitly report millisecond quantization and lost fields."""
    records = [c.model_dump(mode="json") for c in segments]
    loss = {"format": kind, "time_quantization": "none", "lost_fields": []}
    if kind == "json":
        return encoded({"schema_version": 1, "segments": records,
                        "provenance": provenance | {"untimed_backend_text": untimed}}), loss
    if kind == "text":
        text = "\n".join([r["text"] for r in records] + [r["text"] for r in untimed])
        loss["lost_fields"] = ["ids", "times", "words", "speakers", "provenance"]
        return text.encode(), loss
    if untimed:
        raise ValueError("Untimed backend text cannot be exported as timed captions")
    loss.update(time_quantization="nearest millisecond, half up; at most0.5ms per endpoint",
                lost_fields=["words", "provenance"] + ([] if kind == "tsv" else ["speakers", "source_ids"]))
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
    if kind == "tsv":
        writer.writerow(["id", "start_ms", "end_ms", "text", "speaker_id"])
    elif kind == "vtt":
        stream.write("WEBVTT\n\n")
    for index, record in enumerate(records, 1):
        start, end = _milliseconds(record["start_seconds"]), _milliseconds(record["end_seconds"])
        if end <= start:
            raise ValueError("Millisecond quantization collapses an actual positive caption interval")
        if kind == "tsv":
            writer.writerow([record["id"], start, end, record["text"], record["speaker_id"] or ""])
        elif kind in {"srt", "vtt"}:
            if "\r" in record["text"] or any(not line.strip() for line in record["text"].split("\n")):
                raise ValueError("SRT/VTT cue text contains unsupported blank/control lines; use full JSON or TSV")
            separator = "," if kind == "srt" else "."
            stream.write(f"{index}\n{_clock(start, separator)} --> {_clock(end, separator)}\n{record['text']}\n\n")
        else:
            raise ValueError("Unsupported transcript export format")
    return stream.getvalue().encode(), loss


def artifact_record(directory: Path, path: Path, role="retained_observation") -> dict:
    """Bind every regular owned output; observation files are evidence, not discarded metadata."""
    relative = path.relative_to(directory).as_posix()
    checked_path(str(path))
    from .media_local_io import _copy_hash
    sha, size = _copy_hash(path, max_bytes=8 * 1024 * 1024)
    data = read_payload({"path": str(path), "bytes": size, "sha256": sha})
    return {"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "role": role}


async def verify_artifacts(directory: Path, artifacts: list) -> None:
    """Read complete contained regular artifacts under the existing nofollow/hash policy."""
    seen, total = set(), 0
    for record in artifacts:
        relative = Path(record["path"])
        if relative.is_absolute() or ".." in relative.parts or record["path"] in seen:
            raise ValueError("Retained transcript artifact has a duplicate or escaping path")
        seen.add(record["path"])
        path = checked_path(str(directory / relative))
        actual = _empty_artifact(path) if record["bytes"] == 0 else await copy_hash(path)
        if actual != (record["sha256"], record["bytes"]):
            raise ValueError("Retained transcript artifact bytes changed")
        total += record["bytes"]
    if len(seen) > 32 or total > 20 * 1024 * 1024:
        raise ValueError("Transcript retained evidence exceeds32files/20MiB")


def _empty_artifact(path: Path) -> tuple[str, int]:
    """An empty text/caption export is valid; the media-source hasher correctly rejects it."""
    with _open_regular(path) as stream:
        before = os.fstat(stream.fileno())
        if before.st_size != 0 or stream.read(1):
            raise ValueError("Expected empty transcript export changed")
        after, current = os.fstat(stream.fileno()), path.lstat()
        def identity(stat):
            return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
        if identity(before) != identity(after) or identity(before) != identity(current):
            raise ValueError("Empty transcript export identity changed")
    return hashlib.sha256(b"").hexdigest(), 0


async def read_receipt(directory: str, expected_sha256: str) -> tuple[Path, dict, dict]:
    """An external receipt digest must match before any cached metadata is trusted."""
    root = checked_path(directory)
    path = checked_path(str(root / "receipt.json"))
    if (await copy_hash(path))[0] != expected_sha256:
        raise ValueError("Transcript receipt differs from the independently trusted SHA256")
    receipt = strict_json(read_payload({"path": str(path), "sha256": expected_sha256, "bytes": path.stat().st_size}))
    if receipt.get("schema_version") != 1 or receipt.get("status") not in {"complete", "planned", "partial", "failed"}:
        raise ValueError("Retained transcript receipt is malformed")
    await verify_artifacts(root, receipt["artifacts"])
    result_record = next(r for r in receipt["artifacts"] if r["path"] == "transcript-result.json")
    result = strict_json(read_payload({**result_record, "path": str(root / result_record["path"])}))
    if any(result.get(key) != receipt.get(key) for key in ("status", "source", "request_sha256", "operation")):
        raise ValueError("Retained result differs from its receipt commitments")
    if (await copy_hash(path))[0] != expected_sha256:
        raise ValueError("Transcript receipt changed during readback")
    return root, receipt, result
