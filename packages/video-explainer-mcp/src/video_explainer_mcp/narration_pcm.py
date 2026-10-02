"""Own PCM measurement, deterministic tone events and exact sample concatenation.

Requirements were independently adapted from Qwen-MM-Plugins (Apache-2.0) and
MoneyPrinterTurbo (MIT, Copyright (c) 2024 Harry); no foreign code is imported.
"""

from array import array
import hashlib
import io
import math
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
import wave

from .file_io import open_regular

MAX_BYTES = 64 * 1024 * 1024
RATE = 24000


def contained(project: Path, relative: str) -> Path:
    """Refuse absolute/traversal paths and every existing symlink component."""
    value = Path(relative)
    if value.is_absolute() or not value.parts or ".." in value.parts:
        raise ValueError("Audio/artifact path must be project-relative without traversal")
    target = project / value
    target.resolve().relative_to(project)
    current = project
    for part in value.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("Audio/artifact path must not contain symlinks")
    return target


def snapshot(path: Path) -> bytes:
    """Read bounded regular bytes and reject inode replacement or mutation."""
    with open_regular(path) as (stream, before):
        if before.st_size > MAX_BYTES:
            raise ValueError("Audio exceeds the 64 MiB byte ceiling")
        body = stream.read(MAX_BYTES + 1)
    after = path.stat()
    if len(body) > MAX_BYTES or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("Audio changed during snapshot readback")
    return body


def atomic_bytes(path: Path, body: bytes) -> None:
    """Fsync and replace only a fresh binary in the exclusively owned run directory."""
    if path.exists() or path.is_symlink():
        raise ValueError("Existing audio artifacts must be preserved")
    descriptor, name = tempfile.mkstemp(prefix=".pcm-", dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def decode(body: bytes) -> tuple[bytes, dict]:
    """Decode complete RIFF PCM16 mono WAV and measure samples, RMS and clipping."""
    if not 44 <= len(body) <= MAX_BYTES or body[:4] != b"RIFF" or body[8:12] != b"WAVE":
        raise ValueError("Expected a bounded complete RIFF WAV")
    if struct.unpack("<I", body[4:8])[0] + 8 != len(body):
        raise ValueError("RIFF size differs from actual WAV bytes")
    data_size = riff_data_size(body)
    try:
        with wave.open(io.BytesIO(body), "rb") as audio:
            channels, width, rate, frames = audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()
            if channels != 1 or width != 2 or audio.getcomptype() != "NONE" or not 1 <= rate <= 192000 or not frames:
                raise ValueError("Expected nonempty uncompressed PCM16 mono WAV")
            pcm = audio.readframes(frames)
    except (wave.Error, EOFError) as error:
        raise ValueError("Corrupt WAV header/codec") from error
    if len(pcm) != frames * channels * width or len(pcm) != data_size:
        raise ValueError("WAV sample data is truncated")
    samples = array("h", pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    rms = math.sqrt(sum(value * value for value in samples) / frames) / 32768
    peak = max(abs(value) for value in samples) / 32768
    clipped = sum(value in (-32768, 32767) for value in samples)
    dbfs = 20 * math.log10(rms) if rms else None
    accepted = clipped == 0 and dbfs is not None and dbfs >= -60
    return pcm, {"frames": frames, "sample_rate": rate, "channels": channels, "sample_width": width,
                 "duration_seconds": frames / rate, "quality": {"accepted": accepted, "rms_dbfs": dbfs,
                 "peak": peak, "clipped_samples": clipped, "measurement": "RMS dBFS, not LUFS"}}


def riff_data_size(body: bytes) -> int:
    """Reject malformed RIFF chunk sizes and incomplete trailing PCM samples."""
    offset, data = 12, []
    while offset < len(body):
        if offset + 8 > len(body):
            raise ValueError("Truncated RIFF chunk header")
        kind, size = body[offset:offset + 4], struct.unpack("<I", body[offset + 4:offset + 8])[0]
        offset += 8 + size + size % 2
        if offset > len(body):
            raise ValueError("Truncated RIFF chunk bytes")
        if kind == b"data":
            data.append(size)
    if len(data) != 1 or data[0] % 2:
        raise ValueError("WAV requires one complete PCM16 sample chunk")
    return data[0]


def qualify(body: bytes) -> tuple[bytes, dict]:
    """Reject corrupt, empty, clipped or silent/very quiet media before acceptance."""
    pcm, measured = decode(body)
    if not measured["quality"]["accepted"]:
        raise ValueError("PCM quality refused: clipping or RMS below -60 dBFS")
    return pcm, measured


def wav(pcm: bytes, rate: int = RATE) -> bytes:
    """Encode actual little-endian PCM16 mono frames without native processing."""
    if len(pcm) % 2 or len(pcm) + 44 > MAX_BYTES:
        raise ValueError("PCM must contain complete bounded samples")
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(pcm)
    return stream.getvalue()


def tone(text: str, rate: float) -> tuple[bytes, list[dict]]:
    """Synthesize actual deterministic word segments; these tones are not speech."""
    words, parts, offset = [], [], 0
    frames = round(0.2 / rate * RATE)
    segment = array("h", (round(8192 * math.sin(2 * math.pi * 440 * index / RATE)) for index in range(frames)))
    if sys.byteorder != "little":
        segment.byteswap()
    for match in re.finditer(r"\S+", text):
        parts.append(segment.tobytes())
        words.append({"word": match.group(), "text_begin": match.start(), "text_end": match.end(),
                      "start_frame": offset, "end_frame": offset + frames, "alignment": "synthetic_event"})
        offset += frames
    if not words:
        raise ValueError("A narration sentence requires non-whitespace text")
    return wav(b"".join(parts)), words


def concatenate(clips: list[bytes], pause_seconds: float) -> tuple[bytes, list[dict]]:
    """Include every measured clip and quantized pause, including the final pause."""
    parts, intervals, offset, expected = [], [], 0, None
    for body in clips:
        pcm, measured = qualify(body)
        identity = (measured["sample_rate"], measured["channels"], measured["sample_width"])
        if expected is not None and identity != expected:
            raise ValueError("Mixed WAV formats cannot be concatenated without qualified conversion")
        expected = identity
        pause = round(pause_seconds * measured["sample_rate"])
        intervals.append({"start_frame": offset, "audio_end_frame": offset + measured["frames"],
                          "end_frame": offset + measured["frames"] + pause, "pause_frames": pause})
        parts.extend((pcm, bytes(pause * 2)))
        offset += measured["frames"] + pause
        if offset * 2 + 44 > MAX_BYTES:
            raise ValueError("Concatenation exceeds the 64 MiB byte ceiling")
    if expected is None:
        raise ValueError("No complete sentence WAVs to concatenate")
    return wav(b"".join(parts), expected[0]), intervals


def artifact(path: Path, project: Path, body: bytes) -> dict:
    """Bind exact measured WAV bytes to their project-relative file identity."""
    _, measured = qualify(body)
    return {"path": str(path.relative_to(project)), "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body), **measured}
