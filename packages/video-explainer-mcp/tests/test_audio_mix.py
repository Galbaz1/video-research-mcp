"""Licensed local audio mix: recipe, rights/scope, cache lifecycle and signal QA with a mocked media runner."""

import array
import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
import json
import subprocess
import sys
import tempfile
import wave

import pytest
from pydantic import ValidationError

import video_explainer_mcp.audio_mix as audio_mix
from video_explainer_mcp.models.audio_mix import AudioMixRequest
from video_explainer_mcp.models.materials import PinnedFile
from video_explainer_mcp.tools.audio_mix import explainer_audio_mix

NOW = datetime.now(timezone.utc)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture()
def project(tmp_path, monkeypatch):
    path = tmp_path / "projects" / "mix"
    path.mkdir(parents=True)
    monkeypatch.setenv("EXPLAINER_PATH", str(tmp_path))
    monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(path.parent))
    return path


def asset(project, name, commercial=True, valid=True):
    data = f"fixture-{name}".encode()
    (project / f"{name}.wav").write_bytes(data)
    rights = {"source_sha256": sha(data), "license": "CC-BY-4.0", "license_url": "https://example.invalid/cc-by",
              "credit": f"Fixture {name}", "principal": "editor", "use_allowed": True, "commercial_use": commercial,
              "retrieved_at": (NOW - timedelta(days=1)).isoformat(), "valid_until": (NOW + timedelta(days=1 if valid else -0.5)).isoformat()}
    body = json.dumps(rights).encode()
    (project / f"{name}.rights.json").write_bytes(body)
    return {"source": {"path": f"{name}.wav", "sha256": sha(data)}, "rights": {"path": f"{name}.rights.json", "sha256": sha(body)}}


def storyboard(project, scenes=(("s0", 0.5), ("s1", 2.0), ("s2", 0.5)), name="storyboard.json"):
    body = json.dumps({"scenes": [{"id": i, "audio_duration_seconds": d} for i, d in scenes],
                       "total_duration_seconds": sum(d for _, d in scenes)}).encode()
    (project / name).write_bytes(body)
    return {"path": name, "sha256": sha(body)}


def request(project, **change):
    cues = [{"cue_id": "voice", "role": "narration", "scene_id": "s1", **asset(project, "voice"), "start_seconds": 0.5, "duration_seconds": 2.0,
             "fade_in_seconds": 0.1, "fade_out_seconds": 0.2},
            {"cue_id": "bed", "role": "music", **asset(project, "bed"), "start_seconds": 0, "duration_seconds": 3.0,
             "gain_db": -12, "fade_in_seconds": 0.5, "fade_out_seconds": 0.5},
            {"cue_id": "hit", "role": "sfx", "scene_id": "s2", **asset(project, "hit"), "start_seconds": 2.5, "duration_seconds": 0.25}]
    return AudioMixRequest.model_validate({"principal": "editor", "storyboard": storyboard(project), "total_seconds": 3.0,
                                           "cues": cues} | change)


@pytest.fixture()
def runner(monkeypatch):
    """Mock only FFmpeg: write a 16-bit stereo WAV to the requested target; record calls."""
    state = {"calls": [], "frames": None, "level": 1000}
    monkeypatch.setattr(audio_mix, "codec_executables", lambda: {"ffmpeg": {"path": "/mock/ffmpeg", "sha256": "f" * 64}})

    async def run(command, timeout, **_):
        state["calls"].append(command)
        rate = int(command[command.index("-ar") + 1])
        frames = state["frames"] or round(float(command[command.index("-t") + 1]) * rate)
        with wave.open(command[-1], "wb") as out:
            out.setnchannels(2)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(array.array("h", [state["level"]] * frames * 2).tobytes())
        return b"", b""
    monkeypatch.setattr(audio_mix, "run_media_process", run)
    return state


def test_recipe_levels_fades_placement_and_ducking_are_deterministic(project):
    first = audio_mix.recipe(request(project), ["a", "b", "c"], "out.wav", "ffmpeg")
    assert first == audio_mix.recipe(request(project), ["a", "b", "c"], "out.wav", "ffmpeg")
    graph = first[first.index("-filter_complex") + 1]
    assert "volume=-12.0dB" in graph and "afade=t=in:d=0.1" in graph and "afade=t=out:st=1.8:d=0.2" in graph
    assert "adelay=500|500" in graph and "adelay=2500|2500" in graph
    assert "sidechaincompress=threshold=0.02:ratio=7.0:attack=50:release=400" in graph
    assert "normalize=0" in graph and first[-2:] == ["-n", "out.wav"] and "out.wav" not in first[:first.index("-filter_complex")]
    assert first.count("-protocol_whitelist") == 3 and first[first.index("-i") - 4:first.index("-i")] == ["-protocol_whitelist", "file,pipe", "-f", "wav"]


def test_scope_bounds_refused_at_the_model(project):
    with pytest.raises(ValidationError, match="past total_seconds"):
        request(project, total_seconds=2.0)
    base = request(project).model_dump(mode="json")
    twice = base | {"cues": base["cues"] + [base["cues"][1] | {"cue_id": "bed-again"}]}
    with pytest.raises(ValidationError, match="layered twice"):
        AudioMixRequest.model_validate(twice)


async def test_rights_refusals(project, runner):
    req = request(project)
    (project / "bed.rights.json").write_bytes(json.dumps(json.loads((project / "bed.rights.json").read_text()) | {"commercial_use": False}).encode())
    stale = req.model_dump(mode="json")
    assert "changed" in (await explainer_audio_mix(project.name, AudioMixRequest.model_validate(stale)))["error"]
    stale["cues"][1]["rights"]["sha256"] = sha((project / "bed.rights.json").read_bytes())
    assert "error" not in (await explainer_audio_mix(project.name, AudioMixRequest.model_validate(stale | {"duck_db": 1})))
    result = await explainer_audio_mix(project.name, AudioMixRequest.model_validate(stale | {"commercial": True}))
    assert "commercial" in result["error"]
    expired = request(project)
    expired.cues[2].rights = PinnedFile.model_validate(asset(project, "hit", valid=False)["rights"])
    assert "stale" in (await explainer_audio_mix(project.name, expired))["error"]
    assert len(runner["calls"]) == 1  # only the permitted non-commercial mix rendered


async def test_mix_receipt_qa_and_cached_retry_without_second_render(project, runner):
    first = await explainer_audio_mix(project.name, request(project))
    assert first["success"] and first["cached"] is False and len(runner["calls"]) == 1
    assert [s["license"] for s in first["sources"]] == ["CC-BY-4.0"] * 3 and first["sources"][1]["credit"] == "Fixture bed"
    assert first["qa"]["duration_seconds"] == 3.0 and first["qa"]["clipping"] is False and first["qa"]["peak_dbfs"] < 0
    assert first["qa"]["listening_quality"] == "UNQUALIFIED" and first["provider_calls"] == 0
    assert sha((project / first["output"]).read_bytes()) == first["output_sha256"]
    again = await explainer_audio_mix(project.name, request(project))
    assert again["cached"] is True and again["output_sha256"] == first["output_sha256"] and len(runner["calls"]) == 1
    changed = await explainer_audio_mix(project.name, request(project, duck_db=6))
    assert changed["cache_key"] != first["cache_key"] and len(runner["calls"]) == 2


async def test_clipping_and_wrong_duration_publish_no_final_output(project, runner):
    runner["level"] = 32767
    clipped = await explainer_audio_mix(project.name, request(project))
    assert "clips" in clipped["error"]
    runner["level"], runner["frames"] = 1000, 10
    short = await explainer_audio_mix(project.name, request(project, duck_db=3))
    assert "duration differs" in short["error"]
    assert not list(project.glob("audio-mix-*")) and not list(project.glob(".audio-mix-*"))


async def test_cues_must_match_storyboard_scenes(project, runner):
    off = request(project).model_dump(mode="json")
    off["cues"][2]["scene_id"] = "s1"
    assert "storyboard scene s1" in (await explainer_audio_mix(project.name, AudioMixRequest.model_validate(off)))["error"]
    late = request(project).model_dump(mode="json")
    late["cues"][0]["start_seconds"] = 0.6
    late["cues"][0]["duration_seconds"] = 1.9
    assert "storyboard" in (await explainer_audio_mix(project.name, AudioMixRequest.model_validate(late)))["error"]
    assert "total" in (await explainer_audio_mix(project.name, request(project, storyboard=storyboard(project, (("s0", 1.0),), "short.json"))))["error"]
    assert runner["calls"] == []


async def test_changed_source_refuses_cached_success_and_busy_project_refuses(project, runner):
    req = request(project)
    first = await explainer_audio_mix(project.name, req)
    assert first["sources"][0]["source_path"] == "voice.wav" and first["sources"][0]["rights_path"] == "voice.rights.json"
    assert first["timing"]["scenes"]["s1"] == [0.5, 2.5] and "UNQUALIFIED" in first["ducking"]
    (project / "voice.wav").write_bytes(b"replaced")
    assert "source bytes changed" in (await explainer_audio_mix(project.name, req))["error"]
    from video_explainer_mcp.planning import plan_transaction
    with plan_transaction(project, create=True):
        assert "busy" in (await explainer_audio_mix(project.name, req))["error"]


async def test_rights_changed_during_mix_refuses_publication(project, runner, monkeypatch):
    req = request(project)
    original = runner_run = audio_mix.run_media_process

    async def mutate(command, timeout, **kwargs):
        await runner_run(command, timeout, **kwargs)
        (project / "voice.rights.json").write_text("{}")
    monkeypatch.setattr(audio_mix, "run_media_process", mutate)
    result = await explainer_audio_mix(project.name, req)
    assert "error" in result and not list(project.glob("audio-mix-*.wav")) and original


@pytest.mark.parametrize("field", ["sources", "qa", "cache_key", "oversize"])
async def test_corrupt_cached_receipt_refuses_success(project, runner, field):
    """Cached bytes cannot promote altered provenance or QA into a successful receipt."""
    req = request(project)
    first = await explainer_audio_mix(project.name, req)
    path = project / (first["output"] + ".json")
    value = json.loads(path.read_text())
    if field == "sources":
        value["sources"][0]["license"] = "forged"
    elif field == "qa":
        value["qa"]["clipping"] = True
    elif field == "cache_key":
        value["cache_key"] = "0" * 64
    else:
        value["padding"] = "x" * (1024 * 1024)
    path.write_text(json.dumps(value))
    result = await explainer_audio_mix(project.name, req)
    assert "error" in result
    assert len(runner["calls"]) == 1


@pytest.mark.parametrize("scenes", [(("s0", -1.0), ("s1", 4.0)), (("s0", 1.5), ("s0", 1.5))])
async def test_invalid_storyboard_windows_refuse_before_mix(project, runner, scenes):
    """A pinned storyboard still requires positive, uniquely identified scene intervals."""
    req = request(project)
    req.cues = [req.cues[1]]
    req.storyboard = PinnedFile.model_validate(storyboard(project, scenes, "invalid-storyboard.json"))
    result = await explainer_audio_mix(project.name, req)
    assert "error" in result
    assert runner["calls"] == []


async def test_truncated_pcm_refuses_publication(project, runner, monkeypatch):
    """A retained full-duration header cannot replace actually present PCM frames."""
    run = audio_mix.run_media_process

    async def truncate(command, timeout, **kwargs):
        await run(command, timeout, **kwargs)
        with open(command[-1], "r+b") as stream:
            stream.truncate(444)
        return b"", b""

    monkeypatch.setattr(audio_mix, "run_media_process", truncate)
    result = await explainer_audio_mix(project.name, request(project))
    assert "error" in result
    assert not list(project.glob("audio-mix-*.wav"))


def test_rolling_tail_reports_peak_before_short_final_chunk(project):
    """The final ten milliseconds span read blocks and retain their highest peak."""
    req = request(project)
    frames = 65537
    req.total_seconds = frames / req.sample_rate
    samples = array.array("h", [0] * (frames * 2))
    samples[-400] = 15000
    path = project / "tail.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(req.sample_rate)
        out.writeframes(samples.tobytes())
    assert audio_mix.measure(path, req)["tail_peak_dbfs"] == -6.79


def test_growing_output_refuses_before_reading_beyond_the_byte_cap(project, monkeypatch):
    """A small file whose header declares PCM beyond the cap refuses before reads, although it grows on read."""
    req = request(project)
    frames = 2048
    req.total_seconds = frames / req.sample_rate
    path = project / "growing.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(req.sample_rate)
        out.writeframes(bytes(frames * 4))
    with open(path, "r+b") as stream:
        stream.truncate(444)
    served = []
    real = audio_mix.open_regular

    class Growing:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, size=-1):
            with open(path, "ab") as tail:
                tail.write(bytes(max(size, 0)))
            data = self.stream.read(size)
            served.append(len(data))
            return data

    @contextlib.contextmanager
    def growing(target):
        with real(target) as (stream, info):
            yield Growing(stream), info

    monkeypatch.setattr(audio_mix, "MAX_OUTPUT_BYTES", 4096)
    monkeypatch.setattr(audio_mix, "open_regular", growing)
    with pytest.raises(ValueError, match="declares"):
        audio_mix.measure(path, req)
    assert sum(served) <= 4096


def test_output_replaced_with_fifo_refuses_bounded_read(project):
    """Substitution after a successful hash must refuse without opening a blocking FIFO."""
    req = request(project)
    path = project / "replaced.wav"
    path.write_bytes(b"regular before pin")
    code = """
import os, sys
from pathlib import Path
from video_explainer_mcp.audio_mix import measure
from video_explainer_mcp.models.audio_mix import AudioMixRequest
from video_explainer_mcp.render_storyboard_sources import file_pin
p = Path(sys.argv[1])
file_pin(p, 1024)
p.unlink()
os.mkfifo(p)
try:
    measure(p, AudioMixRequest.model_validate_json(sys.argv[2]))
except ValueError as error:
    print(str(error))
else:
    raise AssertionError('FIFO accepted')
"""
    result = subprocess.run([sys.executable, "-c", code, str(path), req.model_dump_json()],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=3)
    assert result.returncode == 0 and "regular" in result.stdout


@pytest.mark.parametrize("failure", ["clipping", "cancellation", "after_publication"])
async def test_cleanup_error_preserves_primary_and_removes_published_output(project, runner, monkeypatch, failure):
    """Cleanup refusal retains the primary failure/cancellation and exact output ownership."""
    cleanup = tempfile.TemporaryDirectory.cleanup

    def refuse(directory):
        cleanup(directory)
        raise OSError("cleanup refused")

    monkeypatch.setattr(tempfile.TemporaryDirectory, "cleanup", refuse)
    if failure == "clipping":
        runner["level"] = 32767
    elif failure == "cancellation":
        async def cancel(*args, **kwargs):
            raise asyncio.CancelledError("primary cancellation")
        monkeypatch.setattr(audio_mix, "run_media_process", cancel)
        with pytest.raises(asyncio.CancelledError) as caught:
            await explainer_audio_mix(project.name, request(project))
        assert any("cleanup" in note for note in caught.value.__notes__)
        return
    result = await explainer_audio_mix(project.name, request(project))
    assert "clips" in result["error"] if failure == "clipping" else "cleanup refused" in result["error"]
    assert not list(project.glob("audio-mix-*.wav"))
    if failure == "clipping":
        assert any("cleanup" in note for note in result["cleanup_liability"])
