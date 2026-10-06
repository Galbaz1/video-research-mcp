"""Explicit bounded tutorial inputs and exclusive durable artifact bytes."""

import hashlib
import json
import os
import stat
import struct
import zlib

from ..media_local_io import _open_regular
from ..media_snapshot import checked_path, copy_hash

MAX_PDF_BYTES = 8 * 1024 * 1024
MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_PAGE_BYTES = 32 * 1024 * 1024
MAX_STAGE_BYTES = 48 * 1024 * 1024
MAX_PAGE_PIXELS = 1_000_000
MAX_TOTAL_PAGE_PIXELS = 24_000_000
MAX_PAGES = 40
class NoteError(ValueError):
    """A known local tutorial contract refusal with safe actionable diagnostic text."""


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".mpeg", ".mpg", ".m4v", ".wmv", ".3gp"}


def digest(data):
    """Commit the same bytes used in an artifact or renderer."""
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    """Serialize finite lineage without ambiguous or varying whitespace."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode()


def identity(path):
    """Bind a concrete regular file revision or exact absent destination."""
    if not path.exists() and not path.is_symlink():
        return None
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode):
        raise PermissionError("Tutorial inputs and destination must be regular files")
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def admit(request):
    """Fence all paths and overwrite intent before hashing or any filesystem mutation."""
    source, output = checked_path(request.file_path), checked_path(request.output_path)
    if source.suffix.lower() not in VIDEO_EXTENSIONS or identity(source) is None:
        raise NoteError("Tutorial input must be an existing supported local video")
    if output.suffix.lower() != ".pdf" or not output.parent.is_dir():
        raise NoteError("Tutorial output requires .pdf and an existing local parent directory")
    source_identity, output_identity = identity(source), identity(output)
    if source == output or (output_identity and source_identity[:2] == output_identity[:2]):
        raise NoteError("Tutorial destination must differ from the original input")
    if output_identity and not request.overwrite:
        raise NoteError("Tutorial destination exists; explicit overwrite is required")
    if output_identity and output_identity[2] > MAX_PDF_BYTES:
        raise NoteError("Existing tutorial PDF exceeds the 8 MiB destination bound")
    if request.perception and checked_path(request.perception.file_path) != source:
        raise NoteError("Perception must use the exact selected tutorial source")
    if request.perception and not request.dry_run and (
        request.perception.dry_run or not request.perception.authorize_submission
    ):
        raise PermissionError("Tutorial perception requires its explicit workflow submission grant")
    parent = output.parent.stat()
    return source, output, source_identity, output_identity, (parent.st_dev, parent.st_ino)


async def source_record(source, expected, original_identity):
    """Hash read-only and bind the original identity without creating a view/cache."""
    sha256, size = await copy_hash(source)
    if sha256 != expected or identity(source) != original_identity:
        raise NoteError("Tutorial original source SHA256 or identity changed")
    return {"path": str(source), "sha256": sha256, "bytes": size}


def read_bytes(path, maximum):
    """Read a regular no-follow file once under an explicit byte ceiling."""
    path = checked_path(str(path))
    with _open_regular(path) as reader:
        before = os.fstat(reader.fileno())
        if before.st_size > maximum:
            raise NoteError("Tutorial artifact exceeds its byte ceiling")
        data = reader.read(maximum + 1)
        after = os.fstat(reader.fileno())
    if len(data) > maximum or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ) or identity(path) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns):
        raise NoteError("Tutorial artifact changed during read")
    return data


def write_bytes(path, data):
    """Write one exclusively owned regular artifact and retain exact readback identity."""
    path = checked_path(str(path))
    created = None
    try:
        with path.open("xb") as writer:
            os.fchmod(writer.fileno(), 0o600)
            value = os.fstat(writer.fileno())
            created = value.st_dev, value.st_ino
            writer.write(data)
            writer.flush()
            os.fsync(writer.fileno())
        if read_bytes(path, len(data)) != data:
            raise NoteError("Tutorial artifact readback differs from committed bytes")
        return {"path": str(path), "sha256": digest(data), "bytes": len(data)}
    except BaseException:
        if created is not None and not path.is_symlink() and path.exists():
            value = path.lstat()
            if (value.st_dev, value.st_ino) == created:
                path.unlink()
        raise


def png_shape(data, max_pixels):
    """Verify complete bounded RGB/RGBA PNG structure and decompressed scanline bytes."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise NoteError("Tutorial illustration must be exact PNG bytes")
    offset, compressed, shape, ended = 8, bytearray(), None, False
    while offset + 12 <= len(data):
        size = struct.unpack(">I", data[offset:offset + 4])[0]
        tag = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + size]
        if len(payload) != size or offset + size + 12 > len(data):
            raise NoteError("Truncated tutorial PNG")
        crc = struct.unpack(">I", data[offset + size + 8:offset + size + 12])[0]
        if zlib.crc32(tag + payload) != crc:
            raise NoteError("Tutorial PNG checksum mismatch")
        if tag == b"IHDR":
            if shape or offset != 8 or len(payload) != 13:
                raise NoteError("Invalid tutorial PNG header")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            if not width or not height or width * height > max_pixels or depth != 8 or color not in {2, 6} or any((compression, filtering, interlace)):
                raise NoteError("Unsupported tutorial PNG geometry or encoding")
            shape = width, height, 3 if color == 2 else 4
        elif tag == b"IDAT":
            if shape is None:
                raise NoteError("Tutorial PNG data precedes header")
            compressed.extend(payload)
        elif tag == b"IEND":
            ended = size == 0 and offset + 12 == len(data)
            break
        elif not tag[0] & 32:
            raise NoteError("Unknown critical tutorial PNG chunk")
        offset += size + 12
    if not shape or not ended:
        raise NoteError("Tutorial PNG is incomplete")
    width, height, channels = shape
    expected = height * (1 + width * channels)
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, expected + 1)
    if len(raw) != expected or not decoder.eof or decoder.unused_data or any(raw[i] > 4 for i in range(0, expected, 1 + width * channels)):
        raise NoteError("Tutorial PNG decode/scanline verification failed")
    return width, height


def verify_destination(output, expected, parent_identity):
    """Reject a changed output/parent instead of overwriting a concurrent writer."""
    checked_path(str(output))
    parent = output.parent.stat()
    if (parent.st_dev, parent.st_ino) != parent_identity or identity(output) != expected:
        raise NoteError("Tutorial destination or parent changed before promotion")
