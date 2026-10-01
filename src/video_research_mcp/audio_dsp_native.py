"""File-only FFmpeg loudness observations and source-bound audio visual artifacts."""

import hashlib
import io
import math
import re

from .image_preprocessing import check_worker, image_worker
from .media_local_io import _open_regular
from .media_probe import FORMATS, binary
from .media_process import run_media_process
from .audio_dsp_pcm import MAX_BYTES, RATE


def _command(path):
    """Restrict the three native filter invocations to one owned local PCM file."""
    return [
        binary("ffmpeg"),
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-loglevel",
        "info",
        "-max_alloc",
        "67108864",
        "-threads",
        "1",
        "-filter_threads",
        "1",
        "-filter_complex_threads",
        "1",
        "-protocol_whitelist",
        "file,pipe",
        "-format_whitelist",
        FORMATS,
        "-i",
        str(path),
        "-map_metadata",
        "-1",
    ]


def loudness_summary(stderr):
    """Parse only the terminal ebur128 summary; undefined peaks remain null."""
    text = stderr.decode(errors="replace")
    if " Summary:\n" not in text:
        raise ValueError("FFmpeg did not return a terminal loudness summary")
    summary = text.rsplit(" Summary:\n", 1)[1]
    values = {}
    for key, label, unit in (
        ("integrated_lufs", "I", "LUFS"),
        ("loudness_range_lu", "LRA", "LU"),
        ("true_peak_dbfs", "Peak", "dBFS"),
    ):
        matches = re.findall(rf"^\s*{label}:\s*([-+\w.]+) {unit}\s*$", summary, re.MULTILINE)
        if len(matches) != 1:
            raise ValueError("FFmpeg loudness summary changed its measurement fields")
        value = float(matches[0])
        values[key] = value if math.isfinite(value) else None
    return {
        **values,
        "method": "ffmpeg_ebur128_peak_true",
        "display_precision_decimals": 1,
        "integrated_gate_floor_lufs": -70.0,
        "silence_gate_floor_is_physical_loudness": False,
        "undefined_fields": [key for key, value in values.items() if value is None],
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "standards_conformance_verified": False,
    }


async def loudness(owned, selection):
    """Retain a completed local filter observation without claiming EBU/ITU qualification."""
    command = _command(selection["path"]) + ["-af", "ebur128=peak=true", "-f", "null", "-"]
    _, stderr = await run_media_process(command, owned.remaining())
    return loudness_summary(stderr)


def read_png(path, dimensions, cancelled, deadline):
    """Decode and hash one bounded immutable PNG buffer with exact declared geometry."""
    from PIL import Image

    check_worker(cancelled, deadline)
    with _open_regular(path) as reader:
        data = reader.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Audio visual artifact exceeds8MiB")
    with Image.open(io.BytesIO(data), formats=["PNG"]) as image:
        if image.size != dimensions:
            raise ValueError("Audio visual artifact dimensions differ from the declared grid")
        image.verify()
    check_worker(cancelled, deadline)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "mime": "image/png",
        "width": dimensions[0],
        "height": dimensions[1],
    }


async def render_views(owned, selection, source_sha256):
    """Export two exclusive small PNGs, binding source clock and PCM identity to each."""
    artifacts = []
    for role, dimensions, expression in (
        ("waveform", (512, 128), "showwavespic=s=512x128:split_channels=1:scale=lin:draw=full"),
        ("spectrogram", (256, 128), "showspectrumpic=s=256x128:legend=0:scale=log:win_func=hann"),
    ):
        path = owned.directory / (role + ".png")
        command = _command(selection["path"]) + [
            "-lavfi",
            expression,
            "-frames:v",
            "1",
            "-threads",
            "1",
            "-c:v",
            "png",
            "-fs",
            str(MAX_BYTES),
            "-f",
            "image2",
            "-n",
            str(path),
        ]
        await run_media_process(command, owned.remaining())
        artifact = await image_worker(read_png, path, dimensions, deadline=owned.deadline)
        artifacts.append(
            {
                **artifact,
                "role": role,
                "source_sha256": source_sha256,
                "selected_pcm_sha256": selection["pcm_sha256"],
                "source_reference": selection["source_reference"],
                "horizontal_axis": {
                    "unit": "absolute_source_seconds",
                    "start": selection["source_clock"]["first_seconds"],
                    "end": selection["source_clock"]["end_seconds"],
                },
                "vertical_axis": {
                    "unit": "linear_full_scale" if role == "waveform" else "Hz",
                    "minimum": -1 if role == "waveform" else 0,
                    "maximum": 1 if role == "waveform" else RATE / 2,
                },
                "method": "ffmpeg_" + expression,
            }
        )
    if sum(row["bytes"] for row in artifacts) > MAX_BYTES:
        raise ValueError("Combined audio visual artifacts exceed8MiB")
    return artifacts
