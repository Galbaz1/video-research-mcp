"""Original development fixtures with independently declared source-frame times."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import struct
import zlib

from video_research_mcp.media_process import run_media_process

WIDTH, HEIGHT = 160, 96
CROP = [32, 36, 96, 24]
VFR_MS = [0, 120, 280, 520, 640, 920, 1120]
GLYPHS = {
    "0": [7, 5, 5, 5, 7], "1": [2, 6, 2, 2, 7], "2": [7, 1, 7, 4, 7],
    "3": [7, 1, 7, 1, 7], "4": [5, 5, 7, 1, 1], "5": [7, 4, 7, 1, 7],
    "6": [7, 4, 7, 5, 7], "7": [7, 1, 1, 1, 1], "8": [7, 5, 7, 5, 7],
    "9": [7, 5, 7, 1, 7], "O": [7, 5, 5, 5, 7], "N": [5, 7, 7, 7, 5],
    "F": [7, 4, 6, 4, 4],
}


def digest(path: Path) -> str:
    """Hash the small owned artifact in full."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame_pixels(index: int) -> bytes:
    """Draw binary index bars, bitmap digits and a brief OFF/ON crop state."""
    data = bytearray(bytes((24, 24, 24)) * WIDTH * HEIGHT)

    def rectangle(x, y, width, height, color):
        for row in range(y, y + height):
            offset = (row * WIDTH + x) * 3
            data[offset:offset + width * 3] = bytes(color) * width

    def text(value, x, y, scale):
        for character in value:
            for row, bits in enumerate(GLYPHS[character]):
                for column in range(3):
                    if bits & (1 << (2 - column)):
                        rectangle(x + column * scale, y + row * scale, scale, scale, (255, 255, 255))
            x += 4 * scale

    for bit in range(8):
        color = (240, 240, 240) if index & (1 << bit) else (12, 12, 12)
        rectangle(4 + bit * 19, 4, 14, 20, color)
    state = index in (5, 6)
    rectangle(*CROP, (20, 200, 20) if state else (200, 20, 20))
    text("ON" if state else "OFF", 40, 40, 3)
    text(str(index), 8, 68, 4)
    rectangle(144, 80, 16, 16, (0, 0, 255))
    return bytes(data)


def write_png(path: Path, pixels: bytes, width=WIDTH, height=HEIGHT) -> None:
    """Encode original RGB pixels without an external image library or font."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\0" + pixels[y * width * 3:(y + 1) * width * 3] for y in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
    )


def crop_pixels(pixels: bytes, width: int, box: list[int]) -> bytes:
    """Select the independently authored source RGB crop."""
    x, y, cropped_width, height = box
    return b"".join(pixels[((row * width + x) * 3):((row * width + x + cropped_width) * 3)]
                    for row in range(y, y + height))


def rotate_ccw(pixels: bytes, width=WIDTH, height=HEIGHT) -> bytes:
    """Apply the declared 90-degree display transform to original source pixels."""
    return b"".join(pixels[((x * width + width - 1 - y) * 3):((x * width + width - y) * 3)]
                    for y in range(width) for x in range(height))


def frame_index(pixels: bytes, width: int) -> int:
    """Read the original binary marker with a compression-tolerant threshold."""
    value = 0
    for bit in range(8):
        offset = (12 * width + 11 + bit * 19) * 3
        if sum(pixels[offset:offset + 3]) > 3 * 127:
            value |= 1 << bit
    return value


async def command(args: list[str], commands: list[dict], *, cwd: Path | None = None) -> bytes:
    """Record one bounded owned FFmpeg/ffprobe invocation, including failure."""
    record = {"argv": args, "cwd": str(cwd) if cwd else None}
    commands.append(record)
    try:
        stdout, stderr = await run_media_process(args, 30, cwd=cwd)
    except BaseException as exc:
        record.update(status="failed", error=str(exc))
        raise
    record.update(status="ok", stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                  stderr_sha256=hashlib.sha256(stderr).hexdigest())
    return stdout


async def probe(path: Path, commands: list[dict]) -> dict:
    """Independently read original container/stream/frame information."""
    stdout = await command([
        shutil.which("ffprobe"), "-v", "error", "-protocol_whitelist", "file",
        "-show_format", "-show_streams", "-show_frames", "-of", "json", str(path),
    ], commands)
    return json.loads(stdout)


async def decoded_rgb(path: Path, *, no_rotate=False) -> bytes:
    """Decode a small result artifact through the bounded owned process runner."""
    args = [shutil.which("ffmpeg"), "-nostdin", "-v", "error", "-threads", "1"]
    if no_rotate:
        args.append("-noautorotate")
    args += ["-protocol_whitelist", "file", "-i", str(path), "-frames:v", "1",
             "-threads", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    stdout, _ = await run_media_process(args, 10)
    return stdout


async def _encode(directory: Path, commands: list[dict]) -> None:
    """Build exactly four small original video fixtures and one image."""
    ffmpeg = shutil.which("ffmpeg")
    common = [ffmpeg, "-nostdin", "-v", "error", "-threads", "1", "-filter_threads", "1", "-y"]
    for index in range(12):
        write_png(directory / f"frame-{index:02d}.png", frame_pixels(index))
    write_png(directory / "image.png", frame_pixels(3))
    await command(common + ["-framerate", "10", "-i", "frame-%02d.png", "-frames:v", "12",
                            "-c:v", "libx264rgb", "-qp", "0", "-bf", "0", "-g", "6",
                            "-threads", "1", "cfr.mp4"], commands, cwd=directory)
    lines = ["ffconcat version 1.0"]
    for index, start in enumerate(VFR_MS):
        lines.append(f"file frame-{index:02d}.png")
        end = VFR_MS[index + 1] if index + 1 < len(VFR_MS) else start + 120
        lines.append(f"duration {(end - start) / 1000:.3f}")
    (directory / "vfr.ffconcat").write_text("\n".join(lines) + "\n")
    await command(common + ["-safe", "1", "-f", "concat", "-i", "vfr.ffconcat",
                            "-fps_mode", "vfr", "-c:v", "libx264", "-pix_fmt", "yuv444p",
                            "-crf", "12", "-x264-params", "bframes=2:b-adapt=0:keyint=50:scenecut=0",
                            "-threads", "1", "vfr.mkv"],
                  commands, cwd=directory)
    await command(common + ["-i", "cfr.mp4", "-c", "copy", "-output_ts_offset", "3",
                            "-avoid_negative_ts", "disabled", "offset.mp4"], commands, cwd=directory)
    await command(common + ["-display_rotation", "90", "-i", "cfr.mp4", "-f", "lavfi", "-i",
                            "sine=frequency=440:sample_rate=8000:duration=1.2", "-map", "0:v:0",
                            "-map", "1:a:0", "-c:v", "copy",
                            "-c:a", "aac", "-threads", "1", "-t", "1.2", "rotated.mp4"],
                  commands, cwd=directory)


async def build_fixtures(directory: Path) -> dict:
    """Freeze expected clocks before candidate calls and verify encoded fixture PTS."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("Original fixture generation requires independently installed FFmpeg/ffprobe")
    directory.mkdir(parents=True, exist_ok=True)
    expected = {
        "cfr": {"frame_ms": list(range(0, 1200, 100)), "offset_ms": 0},
        "vfr": {"frame_ms": VFR_MS, "offset_ms": 0},
        "offset": {"frame_ms": list(range(0, 1200, 100)), "offset_ms": 3000},
        "rotated": {"frame_ms": list(range(0, 1200, 100)), "offset_ms": 0},
    }
    declaration = {"purpose": "implementation development; not heldout acceptance", "rights":
                   "Original deterministic RGB bitmap drawings and generated sine; no foreign assets/fonts",
                   "size": [WIDTH, HEIGHT], "crop": CROP, "brief_state_frames": [5, 6],
                   "rotation_degrees": 90, "display_transform": "counterclockwise_90",
                   "audio": {"sample_rate": 8000, "channels": 1}, "expected": expected}
    (directory / "expected-before-generation.json").write_text(json.dumps(declaration, indent=2) + "\n")
    commands = []
    try:
        await _encode(directory, commands)
        fixtures = {}
        for name, labels in expected.items():
            path = directory / (f"{name}.mkv" if name == "vfr" else f"{name}.mp4")
            raw = await probe(path, commands)
            frames = [frame for frame in raw["frames"] if frame["media_type"] == "video"]
            times = [round(float(frame["best_effort_timestamp_time"]) * 1000) for frame in frames]
            assert times == [time + labels["offset_ms"] for time in labels["frame_ms"]], (name, times)
            if name == "vfr":
                assert any(frame["pict_type"] == "B" for frame in frames), "VFR fixture must include B frames"
            if name == "rotated":
                video = next(stream for stream in raw["streams"] if stream["codec_type"] == "video")
                assert any(item.get("rotation") == 90 for item in video.get("side_data_list", []))
                audio = next(stream for stream in raw["streams"] if stream["codec_type"] == "audio")
                assert int(audio["sample_rate"]) == 8000 and audio["channels"] == 1
            assert float(raw["format"]["duration"]) > labels["frame_ms"][-1] / 1000
            fixtures[name] = {**labels, "path": str(path), "sha256": digest(path),
                              "bytes": path.stat().st_size, "oracle": raw}
        fixtures["image"] = {"path": str(directory / "image.png"), "sha256": digest(directory / "image.png")}
        manifest = {**declaration, "fixtures": fixtures, "declaration_sha256": digest(directory / "expected-before-generation.json")}
        (directory / "fixtures.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return manifest
    finally:
        (directory / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
