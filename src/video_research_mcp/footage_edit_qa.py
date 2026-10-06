"""Complete decoded population, signal, black-span and loudness gates for footage edits."""

import hashlib
import math
import re
from fractions import Fraction

from .audio_dsp_native import loudness_summary
from .footage_edit_native import input_command


def frame_hashes(data, expected_count, *, max_frames=256):
    """Require complete SHA256 decoded-frame rows and one positive clock."""
    text = data.decode("ascii")
    clocks = re.findall(r"^#tb 0: (\d+/\d+)\s*$", text, re.MULTILINE)
    if len(clocks) != 1 or Fraction(clocks[0]) <= 0 or "#hash: SHA256" not in text:
        raise ValueError("Decoded frame hashes have no unambiguous SHA256 clock")
    rows = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        columns = [value.strip() for value in line.split(",")]
        if len(columns) != 6 or columns[0] != "0" or not re.fullmatch(r"[a-f0-9]{64}", columns[5]):
            raise ValueError("Decoded frame hash row is malformed")
        dts, pts, duration, size = map(int, columns[1:5])
        if duration <= 0 or size <= 0:
            raise ValueError("Decoded frame hash duration or size is invalid")
        rows.append({"pts": pts, "dts": dts, "duration": duration, "bytes": size,
                     "time_base": clocks[0], "pixel_sha256": columns[5], "pixel_format": "rgb24"})
    if len(rows) != expected_count or not 1 <= len(rows) <= max_frames:
        raise ValueError("Decoded frame hashes do not cover the complete population")
    if any(b["pts"] <= a["pts"] for a, b in zip(rows, rows[1:])):
        raise ValueError("Decoded frame hash clock is unordered")
    return rows


def progress(data, expected_count):
    """Require a successful terminal decoder population, including empty black results."""
    text = data.decode("ascii")
    groups = text.split("progress=")
    if len(groups) < 2 or groups[-1].strip() != "end":
        raise ValueError("Native measurement has no terminal decoder receipt")
    matches = re.findall(r"^frame=(\d+)\s*$", groups[-2], re.MULTILINE)
    if not matches or int(matches[-1]) != expected_count:
        raise ValueError("Native measurement did not decode the full frame population")


def black_summary(stderr):
    """Any actual blackdetect span fails; malformed named records never become absence."""
    text = stderr.decode(errors="replace")
    records = [line for line in text.splitlines() if re.match(r"\[blackdetect @ (?:0x)?[0-9a-fA-F]+\]", line)]
    spans = []
    for line in records:
        match = re.search(r"black_start:([-+\d.eE]+) black_end:([-+\d.eE]+) black_duration:([-+\d.eE]+)\s*$", line)
        if not match:
            raise ValueError("Black-span measurement is malformed")
        start, end, duration = map(float, match.groups())
        if not all(map(math.isfinite, (start, end, duration))) or not 0 <= start <= end or duration < 0:
            raise ValueError("Black-span measurement is invalid")
        spans.append({"start_seconds": start, "end_seconds": end, "duration_seconds": duration})
    if spans:
        raise ValueError("Final contains a detected black span; delivery refused")
    return {"spans": [], "minimum_seconds": .1, "pixel_threshold": .10, "picture_threshold": .98,
            "head_tail_grace_seconds": 0, "stderr_sha256": hashlib.sha256(stderr).hexdigest()}


def loudness_gate(stderr):
    """Require all finite terminal fields and hard delivery bounds for preserved audio."""
    measured = loudness_summary(stderr)
    if measured["undefined_fields"] or not -24 <= measured["integrated_lufs"] <= -10:
        raise ValueError("Final loudness is undefined or outside -24..-10 LUFS")
    if measured["loudness_range_lu"] < 0 or measured["true_peak_dbfs"] > -1.5:
        raise ValueError("Final loudness range or true peak fails the delivery gate")
    return measured


def signal_summary(data, count):
    """Preserve finite signalstats for every measured frame without an automatic look."""
    text = data.decode("ascii")
    rows = re.findall(r"^frame:(\d+)\s+pts:(-?\d+)\s+pts_time:([-+\d.eE]+)\s*$", text, re.MULTILINE)
    fields = {key: re.findall(rf"^lavfi.signalstats.{key}=([-+\d.eE]+)\s*$", text, re.MULTILINE)
              for key in ("YMIN", "YAVG", "YMAX", "SATAVG")}
    if len(rows) != count or any(len(values) != count for values in fields.values()):
        raise ValueError("Signal analysis is absent, incomplete or malformed")
    values = {key: [float(value) for value in items] for key, items in fields.items()}
    if any(not math.isfinite(value) for items in values.values() for value in items):
        raise ValueError("Signal analysis contains nonfinite values")
    if any(int(row[0]) != i or not math.isfinite(float(row[2])) for i, row in enumerate(rows)):
        raise ValueError("Signal analysis frame population is invalid")
    return {"frame_count": count, "method": "ffmpeg_signalstats_all_selected_frames",
            "fields": {key: {"minimum": min(items), "maximum": max(items), "mean": sum(items) / count}
                       for key, items in values.items()}, "metadata_sha256": hashlib.sha256(data).hexdigest(),
            "automatic_style": False, "color_profile_verified": False}


async def signal(work, command, count, filters=""):
    """Read every pre/post signal frame through the bounded existing stdout transport."""
    expression = (filters + "," if filters else "") + "signalstats,metadata=mode=print:file=-"
    data, _ = await work.run(command + ["-vf", expression, "-frames:v", "257", "-an", "-f", "null", "-"])
    return signal_summary(data, count)


async def full_review(path, work, measured, timeline, audio_required, *, max_frames=256):
    """Gate a final only after complete decode, clock, black and terminal audio observations."""
    output = measured["output"]
    expected = [row["timeline_seconds"] for row in timeline["frames"]]
    if output["frame_count"] != len(expected) or len(output["decoded_frame_seconds"]) != len(expected):
        raise ValueError("Final dropped or added source-to-shot frames")
    if any(abs(a - b) > 1e-5 for a, b in zip(output["decoded_frame_seconds"], expected)):
        raise ValueError("Final decoded frame clock differs from the timeline")
    if abs(output["duration_seconds"] - timeline["duration_seconds"]) > 1 / timeline["fps"]:
        raise ValueError("Final duration differs from the exact edit ledger")
    if [output["width"], output["height"]] != timeline["dimensions"] or output["video_codec"] != "h264":
        raise ValueError("Final grid or codec differs from the prepared ledger")
    if (measured["audio"] is not None) != audio_required:
        raise ValueError("Final audio population differs from the explicit plan")
    command = input_command(path) + ["-map", "0:v:0"]
    if audio_required:
        command += ["-map", "0:a:0"]
    command += ["-vf", "blackdetect=d=0.1:pix_th=0.10:pic_th=0.98", "-progress", "pipe:1", "-f", "null", "-"]
    stdout, stderr = await work.run(command)
    progress(stdout, len(expected))
    black = black_summary(stderr)
    audio = {"included": False, "method": "structurally_absent_explicit_an", "loudness": None}
    if audio_required:
        _, stderr = await work.run(input_command(path) + ["-vn", "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-"])
        audio = {"included": True, "loudness": loudness_gate(stderr), "perceptual_sync_verified": False}
    stdout, _ = await work.run(input_command(path) + ["-an", "-vf", "format=rgb24", "-fps_mode", "passthrough",
                                                        "-f", "framehash", "-hash", "sha256", "-"])
    return {"status": "passed", "full_decode": True, "black": black, "audio": audio,
            "decoded_frames": frame_hashes(stdout, len(expected), max_frames=max_frames), "output": output,
            "semantic_visual_human_acceptance_verified": False}
