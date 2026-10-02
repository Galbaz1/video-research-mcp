"""Bound exact operator files and exclusive per-call copies for optional core previews."""

import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import uuid

AUTHORITY_BYTES = 131072
INPUT_BYTES = 8388608
RESULT_BYTES = 4194304


def canonical(value):
    """Require an absolute spelling with no URL, traversal, symlink or path alias."""
    if not isinstance(value, str) or "://" in value or "\x00" in value:
        raise ValueError("Only canonical local paths are admitted")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or value != str(path.resolve()):
        raise ValueError("Local path is relative, aliased or contains a symlink/traversal")
    return path


def read_body(path, maximum):
    """Read a bounded no-follow regular file and join its identity before/after reading."""
    path = canonical(str(path))
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= maximum:
        raise ValueError("Selected file is not regular or exceeds its byte ceiling")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as reader:
        opened = os.fstat(reader.fileno())
        body = reader.read(maximum + 1)
        after = os.fstat(reader.fileno())
    current = path.lstat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if len(body) != before.st_size or any(getattr(before, key) != getattr(row, key) for row in (opened, after, current) for key in fields):
        raise ValueError("Selected file changed during complete readback")
    return body


def sha256(body):
    """Return a complete byte identity rather than a path/mtime cache key."""
    return hashlib.sha256(body).hexdigest()


def verify(row, maximum=INPUT_BYTES):
    """Check exact operator-selected size and SHA, including empty source initializers."""
    if type(row.get("bytes")) is not int or not 0 <= row["bytes"] <= maximum:
        raise ValueError("Selected file byte commitment is invalid")
    if not isinstance(row.get("sha256"), str) or not re.fullmatch("[a-f0-9]{64}", row["sha256"]):
        raise ValueError("Selected file requires a full SHA256")
    body = read_body(row["path"], maximum)
    if len(body) != row["bytes"] or sha256(body) != row["sha256"]:
        raise ValueError("Selected file bytes differ from their exact commitment")
    return body


def parse_json(body):
    """Reject ambiguous duplicate keys and nonfinite numbers in authority/results."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Core JSON contains duplicate keys")
            result[key] = value
        return result
    def invalid(_):
        raise ValueError("Core JSON contains a nonfinite number")
    return json.loads(body, object_pairs_hook=pairs, parse_constant=invalid)


def trusted_json(path, expected, maximum=AUTHORITY_BYTES):
    """Read externally bound metadata without trusting an editable self-receipt."""
    body = read_body(path, maximum)
    if sha256(body) != expected:
        raise ValueError("Metadata differs from the independently trusted SHA256")
    return parse_json(body)


def write_json(path, value, maximum=AUTHORITY_BYTES):
    """Atomically persist owned pending/terminal receipts with joined worker outcomes."""
    body = (json.dumps(value, allow_nan=False, ensure_ascii=False, indent=2) + "\n").encode()
    if len(body) > maximum:
        raise ValueError("Owned core JSON exceeds its byte ceiling")
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as writer:
            os.fchmod(writer.fileno(), 0o600)
            writer.write(body)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": str(path), "sha256": sha256(body), "bytes": len(body)}


def page_selection(pages, maximum):
    """Reject invalid/oversized explicit ranges instead of original fallback or cap bypass."""
    if type(maximum) is not int or not 1 <= maximum <= 4:
        raise ValueError("Explicit max_pages must be an integer from1 through4")
    if pages is None:
        return []
    if not isinstance(pages, str) or not 1 <= len(pages) <= 128:
        raise ValueError("Page selection must be a bounded explicit range")
    selected = set()
    for part in pages.split(","):
        match = re.fullmatch(r"\s*([1-9][0-9]{0,5})(?:-([1-9][0-9]{0,5}))?\s*", part)
        if not match:
            raise ValueError("Page range has an invalid or nonpositive index")
        first, last = int(match[1]), int(match[2] or match[1])
        if last < first or last - first + 1 > maximum:
            raise ValueError("Page range is reversed or exceeds the selected cap")
        selected.update(range(first, last + 1))
        if len(selected) > maximum:
            raise ValueError("Explicit pages cannot bypass max_pages")
    return sorted(selected)


class Inputs:
    """Keep the exact complete operator authority and rejoin every selected original."""

    def __init__(self, path, expected):
        self.path, self.expected = canonical(str(path)), expected
        data = trusted_json(self.path, expected)
        if type(data.get("schema_version")) is not int or data["schema_version"] != 1 or set(data) != {"schema_version", "files"}:
            raise ValueError("Core input authority requires schema_version1 and files")
        rows = data["files"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
            raise ValueError("Core input authority admits1 through32 files")
        self.files = {}
        for row in rows:
            if set(row) != {"path", "sha256", "bytes"} or row["path"] in self.files or not row["bytes"]:
                raise ValueError("Input authority has duplicate, empty or unexpected entries")
            verify(row)
            self.files[row["path"]] = row

    def readback(self):
        """Reject authority or original mutations before/after every handler."""
        trusted_json(self.path, self.expected)
        for row in self.files.values():
            verify(row)

    def selected(self, path):
        """Require the original canonical path, never an arbitrary handler-supplied alias."""
        key = str(canonical(path))
        if key not in self.files:
            raise ValueError("File was not admitted by the operator authority")
        return self.files[key]

    def copy(self, row, directory):
        """Give the original handler a private byte-identical copy, never a user original."""
        body = verify(row)
        path = directory / Path(row["path"]).name
        with path.open("xb") as writer:
            os.fchmod(writer.fileno(), 0o400)
            writer.write(body)
            writer.flush()
            os.fsync(writer.fileno())
        copy = {**row, "path": str(path)}
        verify(copy)
        return copy


def png_grid(body):
    """Bound the selected PNG stored grid before the original Pillow decode can allocate."""
    if len(body) < 33 or body[:8] != b"\x89PNG\r\n\x1a\n" or body[12:16] != b"IHDR":
        raise ValueError("Only the selected PNG image input profile is admitted")
    width, height = struct.unpack_from(">II", body, 16)
    if not width or not height or width * height > 16777216:
        raise ValueError("PNG source grid exceeds16Mi pixels")
    return [width, height]


def require_preview_grid(body, name, arguments):
    """Bound the pinned32-pixel resize grid before original allocation, including EXIF/crop."""
    width, height = png_grid(body)
    from PIL import Image

    with Image.open(io.BytesIO(body)) as image:
        if image.getexif().get(0x0112, 1) in {5, 6, 7, 8}:
            width, height = height, width
    if name == "crop":
        x1, y1, x2, y2 = arguments["box"]
        width, height = (round(x2 / 1000 * width) - round(x1 / 1000 * width),
                         round(y2 / 1000 * height) - round(y1 / 1000 * height))
        if not width or not height:
            raise ValueError("Crop preview grid resolves to an empty area")
    budget = "normal" if name == "crop" else arguments.get("budget", "large" if name == "visualize" else "normal")
    minimum, maximum = 262144, {"small": 262144, "normal": 1048576, "large": 2097152}[budget]
    if width * height < minimum:
        scale = math.sqrt(minimum / (width * height))
        width, height = int(width * scale), int(height * scale)
    if width * height > maximum:
        scale = math.sqrt(maximum / (width * height))
        width, height = int(width * scale), int(height * scale)
    width, height = max(32, round(width / 32) * 32), max(32, round(height / 32) * 32)
    if width * height > 16777216:
        raise ValueError("Original planned preview grid exceeds16Mi pixels")
