"""Derive the exact spatial Matplotlib wheel without its 60 AFM metric assets.

This stdlib-only build preserves payload bytes, TTF fonts and notices. It does
not install, import or qualify Matplotlib. Output is an exclusive directory
containing the original wheel basename and a binding receipt, not a registry
release. Empty structural ZIP directories remain outside wheel RECORD coverage.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import zipfile

WHEEL_NAME = "matplotlib-3.10.9-cp312-cp312-macosx_11_0_arm64.whl"
WHEEL_SHA256 = "41cb28c2bd769aa3e98322c6ab09854cbcc52ab69d2759d681bba3e327b2b320"
DIST_INFO = "matplotlib-3.10.9.dist-info"
RECORD = f"{DIST_INFO}/RECORD"
ATTRIBUTION = f"{DIST_INFO}/SPATIAL_PNG_DERIVATIVE.txt"
AFM_DIRS = {"matplotlib/mpl-data/fonts/afm", "matplotlib/mpl-data/fonts/pdfcorefonts"}
NOTICE = f"""Matplotlib spatial PNG payload derivative; VRM-SPATIAL-PNG/r1
Prepared by the video-research-mcp project, Codex worker, 2026-10-03.
Original: {WHEEL_NAME}
Original archive SHA256: {WHEEL_SHA256}
Upstream attribution: Matplotlib Development Team and John D. Hunter;
all original copyright, license and font notices remain unchanged.
Changes: remove only the 60 .afm metric files directly in mpl-data/fonts/afm
and mpl-data/fonts/pdfcorefonts; rebuild RECORD; add this change summary.
Every other original member's content bytes and permission bits are retained.
ZIP entries are sorted, timestamped 1980-01-01 and stored without compression;
archive comments and extra fields are normalized away.
All 38 TTF fonts, mathtext and Agg/PNG implementation assets remain unchanged.
AFM-dependent PDF/PostScript core-font modes are outside this selected route.
The accompanying receipt binds every retained/excluded/new/rebuilt member.
This derivative retains upstream version/tags and basename in a separate
directory; it is not the original archive or an upstream-endorsed release.
Static payload identity is not legal, native-build, pixel or runtime acceptance.
""".encode()


def _sha256(data: bytes) -> str:
    """Return the content identity used throughout the receipt."""
    return hashlib.sha256(data).hexdigest()


def _record_hash(data: bytes) -> str:
    """Encode a SHA256 digest in wheel RECORD format."""
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


@contextmanager
def _parent_fd(path: Path):
    """Open a filesystem parent without traversing any symlink or '..'."""
    path = path.absolute()
    if ".." in path.parts or path == Path("/"):
        raise ValueError("Unsafe filesystem path")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parent.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def _read_trusted_wheel(path: Path) -> bytes:
    """Admit only the independently pinned filename and exact archive bytes."""
    if path.name != WHEEL_NAME:
        raise ValueError("Wheel filename differs from the pinned input")
    with _parent_fd(path) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise ValueError("Input wheel must be a regular file")
        with os.fdopen(fd, "rb") as stream:
            payload = stream.read()
    if _sha256(payload) != WHEEL_SHA256:
        raise ValueError("Wheel archive SHA256 differs from the pinned input")
    return payload


def _read_archive(payload: bytes) -> dict:
    """Read safe unique regular files and empty structural directories only."""
    members, names = {}, set()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for info in archive.infolist():
            name = info.filename
            parts = name.rstrip("/").split("/")
            mode = info.external_attr >> 16
            canonical = "/".join(parts) + ("/" if info.is_dir() else "")
            if (name != canonical or info.orig_filename != name or "\\" in name or ":" in name
                    or any(part in ("", ".", "..") for part in parts)
                    or any(ord(c) < 32 or ord(c) > 126 for c in name)):
                raise ValueError(f"Unsafe archive member: {name!r}")
            key = name.rstrip("/").casefold()
            if key in names:
                raise ValueError(f"Duplicate archive member: {name!r}")
            names.add(key)
            if info.flag_bits & 1 or info.create_system != 3:
                raise ValueError(f"Unsupported archive member: {name!r}")
            if not (stat.S_ISDIR(mode) if info.is_dir() else stat.S_ISREG(mode)):
                raise ValueError(f"Nonregular archive member: {name!r}")
            data = archive.read(info)
            if len(data) != info.file_size or (info.is_dir() and data):
                raise ValueError(f"Invalid member size: {name!r}")
            members[name] = (info, data)
    files = {name.casefold() for name in members if not name.endswith("/")}
    for name in members:
        parts = name.rstrip("/").casefold().split("/")
        if any("/".join(parts[:i]) in files for i in range(1, len(parts))):
            raise ValueError(f"Archive file/directory conflict: {name!r}")
    _validate_record(members)
    return members


def _validate_record(members: dict) -> None:
    """Require complete exact file coverage, SHA256 and sizes; self is unhashed."""
    if RECORD not in members:
        raise ValueError("Missing wheel RECORD")
    rows = list(csv.reader(io.StringIO(members[RECORD][1].decode("utf-8")), strict=True))
    if any(len(row) != 3 for row in rows):
        raise ValueError("Malformed RECORD row")
    paths = [row[0] for row in rows]
    files = {name for name in members if not name.endswith("/")}
    if len(paths) != len(set(paths)) or set(paths) != files:
        raise ValueError("RECORD coverage differs from regular wheel members")
    for name, digest, size in rows:
        if name == RECORD:
            if digest or size:
                raise ValueError("RECORD self entry must be unhashed and unsized")
        elif digest != _record_hash(members[name][1]) or size != str(len(members[name][1])):
            raise ValueError(f"RECORD hash/size mismatch: {name!r}")


def _identity(name: str, member: tuple) -> dict:
    """Bind content bytes and original file or directory permission bits."""
    info, data = member
    return {"member": name, "bytes": len(data), "sha256": _sha256(data),
            "mode": oct(info.external_attr >> 16), "directory": info.is_dir()}


def _derive(payload: bytes) -> tuple[bytes, dict]:
    """Exercise archive transformation without granting pinned-source admission."""
    original = _read_archive(payload)
    if any(name.rstrip("/").casefold() == ATTRIBUTION.casefold() for name in original):
        raise ValueError("Derivative attribution already exists")
    excluded = {name for name in original
                if Path(name).parent.as_posix() in AFM_DIRS and name.endswith(".afm")}
    members = {name: member for name, member in original.items() if name not in excluded}
    info = zipfile.ZipInfo(ATTRIBUTION)
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    members[ATTRIBUTION] = (info, NOTICE)
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name in sorted(members):
        if not name.endswith("/") and name != RECORD:
            data = members[name][1]
            writer.writerow((name, _record_hash(data), len(data)))
    writer.writerow((RECORD, "", ""))
    members[RECORD] = (original[RECORD][0], record.getvalue().encode())
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, (source_info, data) in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = source_info.external_attr
            archive.writestr(info, data)
    derived = buffer.getvalue()
    _read_archive(derived)
    receipt = {
        "assignment": "VRM-SPATIAL-PNG/r1", "source_admission": "NOT_PERFORMED",
        "original": {"filename": WHEEL_NAME, "bytes": len(payload), "sha256": _sha256(payload)},
        "derived": {"filename": WHEEL_NAME, "bytes": len(derived), "sha256": _sha256(derived)},
        "retained": [_identity(n, original[n]) for n in sorted(original)
                     if n not in excluded and n != RECORD],
        "excluded": [_identity(n, original[n]) for n in sorted(excluded)],
        "added": [_identity(ATTRIBUTION, members[ATTRIBUTION])],
        "rebuilt": [{"original": _identity(RECORD, original[RECORD]),
                     "derived": _identity(RECORD, members[RECORD])}],
        "record_scope": "all regular files; empty structural directories excluded; self unhashed",
        "retained_content_byte_identical": True,
        "archive_normalization": "sorted; ZIP_STORED; 1980-01-01; no comments/extra fields",
        "qualification": "static payload only; legal/native-build/runtime/pixel eligibility unqualified",
    }
    return derived, receipt


def _publish(output: Path, derived: bytes, receipt: dict) -> None:
    """Exclusively create output; clean our files after interrupted publication."""
    receipt_bytes = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    with _parent_fd(output) as parent:
        os.mkdir(output.name, mode=0o700, dir_fd=parent)
        fd = os.open(output.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        created = []
        try:
            for name, data in ((WHEEL_NAME, derived), ("receipt.json", receipt_bytes)):
                file_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                  mode=0o600, dir_fd=fd)
                created.append(name)
                with os.fdopen(file_fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            os.fsync(fd)
        except BaseException:
            for name in created:
                os.unlink(name, dir_fd=fd)
            os.rmdir(output.name, dir_fd=parent)
            raise
        finally:
            os.close(fd)


def build(wheel: Path, output: Path) -> dict:
    """Build this pinned wheel and its receipt without installation or imports."""
    payload = _read_trusted_wheel(wheel)
    derived, receipt = _derive(payload)
    retained = receipt["retained"]
    if (len(receipt["excluded"]) != 60 or len(retained) != 567
            or sum(row["member"].endswith(".ttf") for row in retained) != 38):
        raise ValueError("Pinned font/member inventory differs from the selected payload")
    receipt["source_admission"] = "exact_pinned_archive_sha256_and_filename"
    receipt["builder_sha256"] = _sha256(Path(__file__).read_bytes())
    _publish(output, derived, receipt)
    return receipt


def main() -> None:
    """Accept the pinned input and an absent output directory with existing parent."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    receipt = build(args.wheel, args.output)
    print(json.dumps({key: receipt[key] for key in ("source_admission", "original", "derived")}))


if __name__ == "__main__":
    main()
