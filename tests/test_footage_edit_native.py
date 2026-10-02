"""Synthetic native-boundary controls; no executable, FFmpeg or provider is launched."""

import asyncio
import hashlib
import json
import re
import time
from pathlib import Path

import pytest

from video_research_mcp import footage_edit_native as native
from video_research_mcp.config import get_config
from video_research_mcp.models.footage_edit import PrepareRequest


def sha(path):
    """Hash complete synthetic bytes for actual filesystem commitments."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hash_rows(points, clock="1/1000", color=80):
    """Provide an explicit, complete native SHA256 framehash wire response."""
    rows = ["#hash: SHA256", f"#tb 0: {clock}"]
    rows += [f"0, {p}, {p}, 100, 576, {hashlib.sha256(bytes([color[i] if isinstance(color, list) else color, 40, 60]) * 192).hexdigest()}" for i, p in enumerate(points)]
    return ("\n".join(rows) + "\n").encode()


def video_info(points, duration, *, audio=True, color=80):
    """Describe fake video bytes without claiming that this is playable encoded media."""
    streams = [{"index": 0, "codec_type": "video", "codec_name": "h264", "width": 16, "height": 12,
                "time_base": "1/1000", "avg_frame_rate": "10/1", "r_frame_rate": "10/1",
                "sample_aspect_ratio": "1:1", "start_time": "0", "duration": str(duration)}]
    frames = [{"media_type": "video", "stream_index": 0, "pts": p, "pts_time": str(p / 1000)} for p in points]
    if audio:
        streams += [{"index": 1, "codec_type": "audio", "codec_name": "aac", "time_base": "1/8000",
                     "sample_rate": "8000", "channels": 1}]
        frames += [{"media_type": "audio", "stream_index": 1, "pts": i * 800, "pts_time": str(i / 10),
                    "nb_samples": 800} for i in range(round(duration * 10))]
    return {"format": {"duration": str(duration), "start_time": "0"}, "streams": streams,
            "frames": frames, "fixture_color": color, "frame_colors": [color] * len(points)}


class Transport:
    """Answer the actual process boundary and retain every command for assertions."""

    def __init__(self):
        self.calls = []
        self.fail = None
        self.black = False
        self.hot = False
        self.mutate = None
        self.block = None

    async def run(self, command, timeout):
        self.calls.append((command, timeout))
        if self.block is not None:
            await self.block.wait()
        if self.fail and self.fail(command):
            raise RuntimeError("private diagnostic must stay out of public errors")
        inputs = [Path(command[i + 1]) for i, arg in enumerate(command) if arg == "-i"]
        info = json.loads(inputs[0].read_bytes())
        if self.mutate:
            self.mutate(command)
        if Path(command[0]).name == "ffprobe":
            return json.dumps(info).encode(), b""
        points = [r["pts"] for r in info["frames"] if r["media_type"] == "video"]
        vf = command[command.index("-vf") + 1] if "-vf" in command else ""
        interval = re.search(r"gte\(t,([\d.]+)\)\*lt\(t,([\d.]+)\)", vf)
        if interval:
            start, end = map(float, interval.groups())
            points = [p for p in points if start <= p / 1000 < end]
        if "-filter_complex" in command:
            all_info = [json.loads(p.read_bytes()) for p in inputs]
            count = sum(len([f for f in item["frames"] if f["media_type"] == "video"]) for item in all_info)
            final = video_info([i * 100 for i in range(count)], count / 10, audio="-an" not in command)
            final["frame_colors"] = [c for item in all_info for c in item["frame_colors"]]
            Path(command[-1]).write_text(json.dumps(final))
            return b"", b""
        if "signalstats" in vf:
            value = 82 if "treatment" in info else 80
            rows = [f"frame:{i} pts:{p} pts_time:{p / 1000}\nlavfi.signalstats.YMIN=40\n"
                    f"lavfi.signalstats.YAVG={value}\nlavfi.signalstats.YMAX=200\nlavfi.signalstats.SATAVG=30"
                    for i, p in enumerate(points)]
            return ("\n".join(rows) + "\n").encode(), b""
        if "framehash" in command:
            colors = [info["frame_colors"][[r["pts"] for r in info["frames"] if r["media_type"] == "video"].index(p)] for p in points]
            return hash_rows(points, color=colors), self.showinfo(points)
        if "blackdetect" in vf:
            stderr = b"[blackdetect @ 0xabc] black_start:0.1 black_end:0.3 black_duration:0.2\n" if self.black else b""
            return f"frame={len(points)}\nprogress=end\n".encode(), stderr
        if "-af" in command and "ebur128" in command[command.index("-af") + 1]:
            return b"", b" Summary:\n I: -8.0 LUFS\n LRA: 0.0 LU\n Peak: -0.4 dBFS\n" if self.hot else b" Summary:\n I: -18.0 LUFS\n LRA: 0.0 LU\n Peak: -6.0 dBFS\n"
        if "-c:v" in command and command[command.index("-c:v") + 1] == "png":
            from PIL import Image
            index = int(re.search(r"eq\(n,(\d+)\)", vf)[1])
            with Image.new("RGB", (16, 12), (info["frame_colors"][index], 40, 60)) as image:
                image.save(command[-1], format="PNG")
            return b"", b""
        if "-c:v" in command:
            start, end = map(float, interval.groups())
            output = video_info([p - round(start * 1000) for p in points], end - start,
                                audio="-an" not in command, color=info["fixture_color"])
            if "eq=" in vf:
                output["treatment"] = vf
            Path(command[-1]).write_text(json.dumps(output))
            stderr = self.showinfo(points)
            if "-an" not in command:
                stderr += b"".join(f"[Parsed_ashowinfo_2 @ 0xdef] n:{i} pts:{p * 8} pts_time:{p / 1000} rate:8000 nb_samples:800\n".encode()
                                  for i, p in enumerate(points))
            return b"", stderr
        raise AssertionError(f"Unexpected mocked native operation: {command}")

    @staticmethod
    def showinfo(points):
        """Emit exact named stock showinfo fields consumed by existing original-PTS parser."""
        return b"[Parsed_showinfo_1 @ 0xabc] config in time_base: 1/1000, frame_rate: 10/1\n" + b"".join(
            f"[Parsed_showinfo_1 @ 0xabc] n: {i} pts: {p} pts_time: {p / 1000} fmt:rgb24\n".encode()
            for i, p in enumerate(points))


@pytest.fixture
def boundary(monkeypatch, tmp_path, clean_config):
    """Fence real files and replace only the executable process boundary."""
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    bins = {}
    for name in ("ffmpeg", "ffprobe"):
        path = tmp_path / name
        path.write_bytes(("fake unexecuted " + name).encode())
        bins[name] = str(path)
    for module in (native, __import__("video_research_mcp.media_clip_export", fromlist=["binary"]),
                   __import__("video_research_mcp.media_image_read", fromlist=["binary"])):
        monkeypatch.setattr(module, "binary", lambda name: bins[name])
    transport = Transport()
    monkeypatch.setattr(native, "run_media_process", transport.run)
    sources = []
    for index in range(2):
        path = tmp_path / f"original-{index}.mp4"
        path.write_text(json.dumps(video_info(list(range(0, 1000, 100)), 1, color=80 + index * 40)))
        sources.append(path)
    plan = PrepareRequest.model_validate({"action": "prepare", "brief": "Synthetic boundary controls", "fps": 10,
            "scenes": [{"scene_id": f"S{i}", "file_path": str(path), "expected_source_sha256": sha(path),
                        "start_seconds": .2, "end_seconds": .4, "timeline_start_seconds": i * .2}
                       for i, path in enumerate(sources)]})
    return transport, plan, sources, bins


async def test_binary_identity_is_rejoined_and_timeouts_share_one_deadline(boundary):
    """Changed executable bytes fail before another mocked process invocation."""
    transport, _, _, bins = boundary
    work = native.NativeWork(time.monotonic() + 10)
    await work.admit()
    await work.run([bins["ffprobe"], "-i", str(boundary[2][0])])
    Path(bins["ffprobe"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="bytes changed"):
        await work.run([bins["ffprobe"], "-i", str(boundary[2][0])])
    assert len(transport.calls) == 1
    assert 0 < transport.calls[0][1] <= 10


async def test_native_error_is_redacted_and_missing_binary_is_actionable(boundary, monkeypatch):
    """A process error retains failure without exposing its raw stderr diagnostic."""
    transport, _, sources, bins = boundary
    work = native.NativeWork(time.monotonic() + 10)
    await work.admit()
    transport.fail = lambda _: True
    with pytest.raises(RuntimeError, match="no artifact was accepted") as caught:
        await work.run([bins["ffmpeg"], "-i", str(sources[0])])
    assert "private diagnostic" not in str(caught.value)
    monkeypatch.setattr(native, "binary", lambda _: (_ for _ in ()).throw(ImportError("install FFmpeg separately")))
    with pytest.raises(ImportError, match="install FFmpeg separately"):
        await native.NativeWork(time.monotonic() + 10).admit()


async def test_cancel_awaits_mock_boundary_then_no_additional_command(boundary):
    """Cancellation interrupts the process await without accepting or continuing native work."""
    transport, _, sources, bins = boundary
    work = native.NativeWork(time.monotonic() + 10)
    await work.admit()
    transport.block = asyncio.Event()
    task = asyncio.create_task(work.run([bins["ffmpeg"], "-i", str(sources[0])]))
    await asyncio.sleep(.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(transport.calls) == 1


def test_assemble_command_is_file_only_and_mute_is_structural(boundary, tmp_path):
    """No raw request filters, shell, URL, music, font or audio filler enters assembly."""
    scene = {"duration_seconds": .2, "audio": {"included": False}}
    command = native.assemble_command([scene, scene], tmp_path, tmp_path / "final.mp4")
    assert "-an" in command and "-af" not in command and "-xerror" in command
    assert command.count("-protocol_whitelist") == 2
    assert all(command[i + 1] == "file" for i, arg in enumerate(command) if arg == "-protocol_whitelist")
    assert "concat=n=2:v=1:a=0[v]" in command[command.index("-filter_complex") + 1]
    assert get_config().cache_dir == str(tmp_path / "cache")
