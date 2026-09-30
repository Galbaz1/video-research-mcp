"""Optional file-only Apple Vision execution from exact bundled Swift source."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import platform
import shutil
import tempfile
import time
from pathlib import Path

from .config import get_config
from .media_local_io import _open_regular
from .media_process import run_media_process
from .media_snapshot import checked_path

SOURCE_SHA256 = "3495f965b75391ce7a0b98bd46d87f9532fdd2e7d41f1aafa4c5ad3a1e66fbd6"
MAX_RAW_BYTES = 256 * 1024
MAX_BINARY_BYTES = 8 * 1024 * 1024


def remaining(deadline: float) -> float:
    """Keep compilation and inference under one caller operation deadline."""
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError("Local OCR operation exceeded its configured timeout")
    return value


def _read(path: Path, limit: int) -> bytes:
    """Read a bounded regular buffer and reject a changed filesystem identity."""
    with _open_regular(path) as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > limit:
            raise ValueError("Native OCR cache/source exceeds its byte limit")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    current = path.lstat()
    if len(data) != before.st_size or len(data) > limit or (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns
    ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or (
        current.st_dev, current.st_ino
    ) != (before.st_dev, before.st_ino):
        raise ValueError("Native OCR cache/source changed during readback")
    return data


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def _binding(deadline: float) -> tuple[bytes, dict]:
    """Require macOS, the system compiler and the independently authored source commitment."""
    compiler = Path("/usr/bin/swiftc")
    if platform.system() != "Darwin" or not compiler.is_file():
        raise ImportError("Apple Vision requires macOS and installed /usr/bin/swiftc")
    source = _read(Path(__file__).parent / "native" / "vision_image.swift", 64 * 1024)
    if _sha(source) != SOURCE_SHA256:
        raise ValueError("Bundled Vision source differs from its exact source commitment")
    toolchain = {}
    for name, command in {
        "compiler_version": ["/usr/bin/swiftc", "--version"],
        "selected_compiler": ["/usr/bin/xcrun", "--find", "swiftc"],
        "sdk_path": ["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"],
        "sdk_version": ["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-version"],
    }.items():
        output, _ = await run_media_process(command, remaining(deadline))
        if not output.strip() or len(output) > 4096:
            raise ValueError("Native OCR toolchain identity is missing or oversized")
        toolchain[name] = output.decode("utf-8").strip()
    return source, {
        "source_sha256": _sha(source), "compiler_sha256": _sha(_read(compiler, MAX_BINARY_BYTES)),
        "system": platform.system(), "release": platform.release(),
        "architecture": platform.machine(), "protocol": 1, **toolchain,
        "compile_options": ["-O", "-sdk", toolchain["sdk_path"]],
        "transitive_sdk_framework_bytes": "unverified",
    }


def _cached(directory: Path, binding: dict) -> bytes:
    """Attest cached binary bytes against the complete source/compiler/platform envelope."""
    directory = checked_path(str(directory))
    receipt = json.loads(_read(directory / "receipt.json", 8192))
    binary = _read(directory / "vision-image", MAX_BINARY_BYTES)
    if receipt != {"binding": binding, "binary_sha256": _sha(binary), "bytes": len(binary)}:
        raise ValueError("Native OCR binary cache failed exact readback attestation")
    return binary


async def _binary(deadline: float) -> tuple[bytes, dict]:
    """Build only bundled source into an owned staging directory; atomically cache verified bytes."""
    source, binding = await _binding(deadline)
    root = checked_path(str(Path(get_config().cache_dir) / "native-vision"))
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.stat().st_mode & 0o077:
        raise PermissionError("Native OCR cache directory must be private")
    key = _sha(json.dumps(binding, sort_keys=True).encode())
    target, compiled = checked_path(str(root / key)), False
    if not target.exists():
        staging = Path(tempfile.mkdtemp(prefix="build-", dir=root))
        try:
            owned_source = staging / "vision_image.swift"
            owned_source.write_bytes(source)
            await run_media_process([
                "/usr/bin/swiftc", "-O", "-sdk", binding["sdk_path"],
                "-module-cache-path", str(staging / "modules"),
                str(owned_source), "-o", str(staging / "vision-image"),
            ], remaining(deadline), cwd=staging)
            binary = _read(staging / "vision-image", MAX_BINARY_BYTES)
            (staging / "receipt.json").write_text(json.dumps({
                "binding": binding, "binary_sha256": _sha(binary), "bytes": len(binary),
            }, sort_keys=True))
            owned_source.unlink()
            shutil.rmtree(staging / "modules", ignore_errors=True)
            os.chmod(staging / "vision-image", 0o700)
            try:
                staging.rename(target)
            except OSError as error:
                if error.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                    raise
            compiled = True
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return _cached(target, binding), {**binding, "compiled_this_call": compiled, "cache_key": key}


async def run_vision(image: Path, options: dict, directory: Path, deadline: float) -> tuple[bytes, dict, dict]:
    """Execute a fresh private binary snapshot over one prepared PNG, then validate the protocol."""
    binary, runtime = await _binary(deadline)
    executable = directory / "vision-exec"
    with executable.open("xb") as stream:
        stream.write(binary)
    os.chmod(executable, 0o700)
    try:
        raw, _ = await run_media_process([
            str(executable), str(image), json.dumps(options, separators=(",", ":")),
        ], remaining(deadline), cwd=directory)
    finally:
        executable.unlink(missing_ok=True)
    if len(raw) > MAX_RAW_BYTES:
        raise ValueError("Native OCR raw payload exceeds 256 KiB")
    data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    if not isinstance(data, dict) or set(data) != {
        "protocol", "width", "height", "coordinate_space", "observations"
    } or type(data["protocol"]) is not int or data["protocol"] != 1 or (
        data["coordinate_space"] != "normalized_bottom_left"
    ) or any(type(data[key]) is not int or data[key] <= 0 for key in ("width", "height")) or (
        data["width"] * data["height"] > 1_000_000
    ) or not isinstance(data["observations"], list) or len(data["observations"]) > 128:
        raise ValueError("Native OCR returned an unsupported or oversized protocol")
    return raw, data, {**runtime, "binary_sha256": _sha(binary), "engine": "vision"}
