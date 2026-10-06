"""Executable mock HTTP/process journeys; no service, model, device or FFmpeg calls."""

import base64
import json
from pathlib import Path
import re

import pytest

from video_research_mcp import dubbing_client as client
from video_research_mcp import dubbing_render as render
from video_research_mcp import video_dubbing as workflow
from video_research_mcp.dubbing_contracts import artifact, validate_plan
from video_research_mcp.dubbing_contracts import _analysis_windows
from video_research_mcp.models.video_dubbing import DubbingService, Interval
from tests.test_dubbing_client import wav_bytes


@pytest.mark.parametrize("growth", [False, True])
def test_r139_voice_resume_bounds_response_before_audio(journey, monkeypatch, growth):
    """GIVEN an oversized or growing saved response WHEN resumed THEN refuse before audio."""
    import hashlib
    import os

    root = journey["root"]
    group = root / "work/voices/group"
    folder = group / "key"
    folder.mkdir(parents=True)
    client.write_json(group / "active.json", {"key": "key", "folder": str(folder)})
    intent = folder / "candidate-1.intent.json"
    cache = intent.with_suffix(".response.json")
    raw = b'{"ok":true}'
    expanded = raw + b" " * 32
    cache.write_bytes(raw if growth else expanded)
    client.write_json(intent, {"state": "response_saved", "http_status": 200,
                              "response_sha256": hashlib.sha256(expanded).hexdigest()})
    monkeypatch.setattr(client, "MAX_RESPONSE_BYTES", len(raw))
    original_open, original_fstat = Path.open, os.fstat
    grown = False

    def grow():
        nonlocal grown
        if growth and not grown:
            grown = True
            with original_open(cache, "ab") as stream:
                stream.write(b" " * 32)

    def opening(path, mode="r", *args, **kwargs):
        if path == cache and mode == "rb":
            grow()
        return original_open(path, mode, *args, **kwargs)

    def inspecting(fd):
        result = original_fstat(fd)
        if (result.st_dev, result.st_ino) == (cache.stat().st_dev, cache.stat().st_ino):
            grow()
        return result

    def forbidden_audio(*args):
        raise AssertionError("saved response was accepted before the audio read")

    monkeypatch.setattr(Path, "open", opening)
    monkeypatch.setattr(os, "fstat", inspecting)
    monkeypatch.setattr(client, "audio_bytes", forbidden_audio)
    with pytest.raises(client.DubbingError, match="service_response_cache_changed"):
        render._voice_folder(root, "group", "key", False)
    assert grown == growth


async def test_r131_neighbor_timing_reuses_tts_and_refits(journey):
    """GIVEN unchanged speech WHEN the neighbor moves 2.40 to 2.44 THEN only fit changes."""
    journey['controls']['tts_seconds'] = 1.0
    path, plan_data, transcript = await prepare_and_plan(journey)
    transcript['segments'][0]['end_sec'] = 1.5
    transcript['segments'][1].update(start_sec=1.5, end_sec=2.0)
    transcript['segments'][2]['start_sec'] = 2.40
    plan_data['segments'][0]['end_sec'] = 2.0
    plan_data['segments'][0]['reference']['end_sec'] = 2.0
    plan_data['segments'][1]['start_sec'] = 2.40
    plan_data['segments'][1]['reference']['start_sec'] = 2.40
    transcript_path = journey['root'] / 'analysis/transcript.json'
    client.write_json(transcript_path, transcript)
    plan_data['transcript_sha256'] = artifact(transcript_path)['sha256']
    client.write_json(path, plan_data)
    manifest, plan, first_validation = validate_plan(journey['root'], path)
    first = await render.synthesize_group(journey['root'], manifest, plan, plan.segments[0], first_validation['slots'][0])
    posts = len([url for url, _ in journey['calls'] if url.endswith('/tts')])
    transcript['segments'][2]['start_sec'] = 2.44
    plan_data['segments'][1]['start_sec'] = 2.44
    plan_data['segments'][1]['reference']['start_sec'] = 2.44
    client.write_json(transcript_path, transcript)
    plan_data['transcript_sha256'] = artifact(transcript_path)['sha256']
    client.write_json(path, plan_data)
    manifest, plan, second_validation = validate_plan(journey['root'], path)
    second_slot = second_validation['slots'][0]
    second = await render.synthesize_group(journey['root'], manifest, plan, plan.segments[0], second_slot)
    assert second['raw'] == first['raw']
    assert len([url for url, _ in journey['calls'] if url.endswith('/tts')]) == posts
    assert second['audio']['path'] != first['audio']['path']
    assert second['audio']['sha256'] != first['audio']['sha256']
    assert abs(client.pcm_metadata(client.audio_bytes(Path(second['audio']['path'])))['duration_sec'] - second_slot['duration_sec']) <= 0.002
    assert artifact(Path(first['audio']['path'])) == first['audio']
    resumed = await render.synthesize_group(journey['root'], manifest, plan, plan.segments[0], second_slot)
    assert resumed['audio'] == second['audio']


async def test_r131_remux_preserves_interleaved_tracks(journey, monkeypatch):
    """GIVEN video/subtitle/video WHEN remuxed THEN source order and QA agree."""
    path, _, _ = await prepare_and_plan(journey)
    manifest, _, _ = validate_plan(journey['root'], path)
    source_streams = [{'index': 0, 'codec_type': 'video', 'codec_name': 'h264'},
                      {'index': 1, 'codec_type': 'subtitle', 'codec_name': 'subrip'},
                      {'index': 2, 'codec_type': 'video', 'codec_name': 'hevc'},
                      {'index': 3, 'codec_type': 'audio', 'codec_name': 'aac'}]
    final_streams = []
    source_indices = {}

    async def inspect(path):
        return {'streams': final_streams if str(path).endswith('.mkv') else source_streams,
                'duration_seconds': manifest.duration_sec}

    async def produce(inputs, arguments, output):
        for pos, option in enumerate(arguments):
            if option != '-map':
                continue
            mapping = arguments[pos + 1]
            selected = ([{'codec_type': 'audio', 'codec_name': 'flac'}] if mapping == '1:a:0'
                        else [s for s in source_streams if s['codec_type'] == 'video'] if mapping == '0:v'
                        else [s for s in source_streams if s['codec_type'] == 'subtitle'] if mapping == '0:s?'
                        else [source_streams[int(mapping.split(':')[1])]])
            for stream in selected:
                index = len(final_streams)
                if stream['codec_type'] != 'audio':
                    source_indices[index] = stream['index']
                final_streams.append({**stream, 'index': index})
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b'owned interleaved mock container')
        return artifact(output)

    async def hashed(path, index, *, decoded=False):
        if decoded:
            return 'source-audio' if Path(path).suffix == '.mp4' else 'mixed-audio'
        return str(index if Path(path).suffix == '.mp4' else source_indices[index])

    monkeypatch.setattr(render, 'inspect_media', inspect)
    monkeypatch.setattr(render, 'produce', produce)
    monkeypatch.setattr(render, 'stream_hash', hashed)
    mixed = manifest.no_vocals.model_dump()
    output = await render.remux(journey['root'], manifest, mixed)
    qa = await render.technical_qa(journey['root'], manifest, output, mixed, [{'timing': 'PASS'}])
    assert qa['technical_pass'], qa['checks']


@pytest.fixture
def journey(tmp_path, monkeypatch, clean_config):
    """Own local fake media and replace both HTTP and every process boundary."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("QWEN_MM_DUBBING_SERVER_URL", "http://127.0.0.1:9123")
    monkeypatch.setenv("VRM_DUBBING_LOCAL", "true")
    monkeypatch.setenv("VRM_DUBBING_API_KEY", "synthetic-test-token")
    import video_research_mcp.config as config
    config.get_config().cache_dir = str(tmp_path / "cache")
    config.get_config().local_file_access_root = str(tmp_path)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"owned mock source video; not native media")
    root = tmp_path / "project"
    calls, commands = [], []
    controls = {"tts_seconds": 2.0, "decode_fail": False, "output_duration": 6.0,
                "extra_stream": False, "source_duration": 6.0}

    async def http(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/health"):
            reply = {"model_loaded": True, "status": "ready"}
        elif url.endswith("/separate"):
            payload = json.loads(kwargs["content"])
            reply = {"stems_base64": {key: payload["audio_base64"] for key in ("vocals", "no_vocals")}}
        elif url.endswith("/vad"):
            reply = {"duration": 6.0, "sample_rate": 48000,
                     "segments": [{"start_time": 1.0, "end_time": 3.0},
                                  {"start_time": 3.5, "end_time": 5.5}]}
        elif url.endswith("/tts"):
            pcm = wav_bytes(controls["tts_seconds"])
            reply = {"audio_base64": base64.b64encode(pcm).decode(),
                     "duration_sec": controls["tts_seconds"], "sample_rate": 48000}
        else:
            raise AssertionError(url)
        return 200, json.dumps(reply).encode()

    async def process(argv, timeout, **kwargs):
        commands.append(argv)
        if "ffprobe" in argv[0]:
            final = Path(argv[argv.index("-i") + 1]).suffix == ".mkv"
            streams = [{"index": 0, "codec_type": "video", "codec_name": "h264",
                        "width": 640, "height": 360, "time_base": "1/1000"},
                       {"index": 1, "codec_type": "video", "codec_name": "h264"},
                       {"index": 2, "codec_type": "audio", "codec_name": "flac" if final else "aac"},
                       {"index": 3, "codec_type": "subtitle", "codec_name": "subrip"}]
            if final and controls["extra_stream"]:
                streams.append({"index": 4, "codec_type": "audio", "codec_name": "aac"})
            return json.dumps({"streams": streams, "format": {"duration": str(controls["output_duration"] if final else controls["source_duration"]),
                                                              "start_time": "0"}}).encode(), b""
        if "-f" in argv and argv[argv.index("-f") + 1] == "hash":
            index = int(argv[argv.index("-map") + 1].split(":")[1])
            source_path = Path(argv[argv.index("-i") + 1])
            decoded = "pcm_s16le" in argv
            value = "1" if decoded and source_path.suffix == ".mp4" else "2" if decoded else str(index + 3)
            return ("SHA256=" + value * 64 + "\n").encode(), b""
        if "-f" in argv and argv[argv.index("-f") + 1] == "null":
            if "-af" in argv and "loudnorm" in argv[argv.index("-af") + 1]:
                return b"", b'{"input_i":"-20","input_tp":"-6","input_lra":"3","input_thresh":"-30","target_offset":"0"}'
            if controls["decode_fail"]:
                raise RuntimeError("mock full decode failure")
            return b"", b""
        if "-f" in argv and argv[argv.index("-f") + 1] == "ass":
            return b"[Script Info]\nmock subtitle decode\n", b""
        output = Path(argv[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.suffix == ".mkv":
            output.write_bytes(b"owned mock rendered container; not native media")
        else:
            seconds = float(argv[argv.index("-t") + 1]) if "-t" in argv else 6.0
            if "-af" in argv:
                match = re.search(r"atrim=duration=([0-9.]+)", argv[argv.index("-af") + 1])
                seconds = float(match[1]) if match else seconds
            output.write_bytes(wav_bytes(seconds))
        return b"", b""

    monkeypatch.setattr(client, "exchange", http)
    monkeypatch.setattr(render, "run_media_process", process)
    monkeypatch.setattr("video_research_mcp.media_probe.run_media_process", process)
    monkeypatch.setattr("video_research_mcp.media_probe.shutil.which", lambda name: "/mock/" + name)
    return {"root": root, "source": source, "calls": calls, "commands": commands, "controls": controls}


async def prepare_and_plan(journey):
    """Create genuine owned evidence files through the production preparation path."""
    root, source = journey["root"], journey["source"]
    ready = await workflow.prepare(str(source), str(root), "en", "nl", artifact(source)["sha256"])
    assert ready["analysis_mode"] == "single_full_video"
    vad_hash = artifact(root / "analysis/vad.json")["sha256"]
    transcript = {"schema_version": "vrm/video-dubbing-transcript/v1", "source_movie": str(source),
                  "source_sha256": artifact(source)["sha256"], "vad_sha256": vad_hash,
                  "source_language": "en", "evidence_windows": [{"start_sec": 0.0, "end_sec": 6.0}],
                  "unresolved_issues": [],
                  "segments": [{"segment_id": "SRC_1", "speaker": "A", "source_text": "Hello there",
                                "start_sec": 1.0, "end_sec": 2.0},
                               {"segment_id": "SRC_2", "speaker": "A", "source_text": "Friend",
                                "start_sec": 2.0, "end_sec": 3.0},
                               {"segment_id": "SRC_3", "speaker": "B", "source_text": "Good day",
                                "start_sec": 3.5, "end_sec": 5.5}]}
    client.write_json(root / "analysis/transcript.json", transcript)
    plan = {"schema_version": "vrm/video-dubbing-plan/v1", "source_movie": str(source),
            "source_sha256": artifact(source)["sha256"], "source_language": "en", "target_language": "nl",
            "vad_sha256": vad_hash, "transcript_sha256": artifact(root / "analysis/transcript.json")["sha256"],
            "segments": [{"segment_id": "DUB_0001", "speaker": "A", "source_text": "Hello there Friend",
                          "translated_text": "Hallo beste vriend", "start_sec": 1.0, "end_sec": 3.0,
                          "source_segment_ids": ["SRC_1", "SRC_2"], "merge_reason": "One spoken greeting",
                          "reference": {"start_sec": 1.0, "end_sec": 3.0, "source_segment_ids": ["SRC_1", "SRC_2"],
                                        "selection_reason": "Own clean adjacent speech"}},
                         {"segment_id": "DUB_0002", "speaker": "B", "source_text": "Good day",
                          "translated_text": "Goedendag beste vriend", "start_sec": 3.5, "end_sec": 5.5,
                          "source_segment_ids": ["SRC_3"], "merge_reason": "",
                          "reference": {"start_sec": 3.5, "end_sec": 5.5, "source_segment_ids": ["SRC_3"],
                                        "selection_reason": "Own clean speech"}}]}
    path = root / "plan/translation_plan.json"
    client.write_json(path, plan)
    return path, plan, transcript


async def test_full_mock_journey_reports_unresolved_listening(journey):
    """GIVEN source and authored plan WHEN rendered THEN executable QA stays separate."""
    path, plan, _ = await prepare_and_plan(journey)
    _, _, validation = validate_plan(journey["root"], path)
    assert validation["segment_count"] == 2
    result = await workflow.render_project(str(journey["root"]), str(path), "include")
    assert result["technical_qa"]["technical_pass"] is True
    assert result["valid"] is False and result["listening"]["status"] == "UNRESOLVED"
    assert all(v["listening"] == "UNRESOLVED" for v in result["review_segments"])
    assert "merged_source_segments" in result["review_segments"][0]["flags"]
    assert artifact(Path(result["output"]["path"])) == result["output"]
    commands = journey["commands"]
    assert any("-filter_complex" in argv and "normalize=0" in argv[argv.index("-filter_complex") + 1] for argv in commands)
    assert any("-c:v" in argv and argv[argv.index("-c:v") + 1] == "copy" for argv in commands)
    assert any("-map" in argv and "0:3" in argv for argv in commands)
    assert any("print_format=json" in " ".join(argv) for argv in commands)
    assert any("measured_I=" in " ".join(argv) for argv in commands)
    assert result["native_acceptance"] == "UNQUALIFIED"
    assert all("-protocol_whitelist" in argv and argv[argv.index("-protocol_whitelist") + 1] == "file" for argv in commands)
    assert all("synthetic-test-token" not in " ".join(argv) for argv in commands)


async def test_resume_reuses_stems_and_tts(journey):
    """GIVEN successful service effects WHEN resumed THEN no POST is repeated."""
    path, _, _ = await prepare_and_plan(journey)
    first = await workflow.render_project(str(journey["root"]), str(path), "include")
    count = len([url for url, kwargs in journey["calls"] if kwargs["method"] == "POST"])
    second = await workflow.render_project(str(journey["root"]), str(path), "include")
    assert second["output"] == first["output"]
    assert count == len([url for url, kwargs in journey["calls"] if kwargs["method"] == "POST"])


async def test_plan_revision_preserves_prior_render(journey):
    """GIVEN changed approved translation WHEN rerendered THEN prior bytes remain."""
    path, plan, _ = await prepare_and_plan(journey)
    first = await workflow.render_project(str(journey["root"]), str(path), "include")
    plan["segments"][0]["translated_text"] = "Hallo mijn beste vriend"
    client.write_json(path, plan)
    second = await workflow.render_project(str(journey["root"]), str(path), "include")
    assert first["output"]["path"] != second["output"]["path"]
    assert artifact(Path(first["output"]["path"])) == first["output"]
    assert len(list(journey["root"].glob("renders/*/full/render_report.json"))) == 2


async def test_selective_regeneration_and_default_resume(journey):
    """GIVEN one reviewed group WHEN regenerated THEN reuse all other known effects."""
    path, _, _ = await prepare_and_plan(journey)
    first = await workflow.render_project(str(journey["root"]), str(path), "include")
    before = len([url for url, _ in journey["calls"] if url.endswith("/tts")])
    second = await workflow.render_project(str(journey["root"]), str(path), "include", ["DUB_0001"])
    assert len([url for url, _ in journey["calls"] if url.endswith("/tts")]) == before + 1
    assert first["output"]["path"] != second["output"]["path"]
    resumed = await workflow.render_project(str(journey["root"]), str(path), "include")
    assert resumed["output"] == second["output"]
    assert len([url for url, _ in journey["calls"] if url.endswith("/tts")]) == before + 1


async def test_unknown_effect_blocks_changed_plan_and_regeneration(journey, monkeypatch):
    """GIVEN unknown TTS WHEN plan/name changes THEN no effect is retried."""
    path, plan, _ = await prepare_and_plan(journey)
    original = client.exchange
    tts_calls = []
    async def unknown(url, **kwargs):
        if url.endswith("/tts"):
            tts_calls.append(url)
            raise TimeoutError()
        return await original(url, **kwargs)
    monkeypatch.setattr(client, "exchange", unknown)
    with pytest.raises(client.DubbingError):
        await workflow.render_project(str(journey["root"]), str(path), "include")
    plan["segments"][0]["translated_text"] = "Een gewijzigde goedgekeurde tekst"
    client.write_json(path, plan)
    with pytest.raises(client.DubbingError, match="reconciliation"):
        await workflow.render_project(str(journey["root"]), str(path), "include", ["DUB_0001"])
    assert len(tts_calls) == 1


@pytest.mark.parametrize("field", ["source_sha256", "transcript_sha256", "vad_sha256"])
async def test_hash_joins_fail_before_tts(journey, field):
    """GIVEN a wrong evidence join WHEN rendered THEN no TTS or render runs."""
    path, plan, _ = await prepare_and_plan(journey)
    plan[field] = "0" * 64
    client.write_json(path, plan)
    before = len(journey["commands"])
    with pytest.raises(client.DubbingError):
        await workflow.render_project(str(journey["root"]), str(path), "include")
    assert len(journey["commands"]) == before
    assert not any(url.endswith("/tts") for url, _ in journey["calls"])


@pytest.mark.parametrize("mutation", ["cross_speaker", "duplicate_coverage", "merge_reason", "overlap",
                                     "reference_speaker", "reference_padding", "source_text", "unknown_id",
                                     "source_language", "nonfinite", "boolean_interval"])
async def test_group_and_reference_boundaries(journey, mutation):
    """GIVEN contradictory grouping/reference evidence WHEN validated THEN reject."""
    path, plan, _ = await prepare_and_plan(journey)
    group = plan["segments"][0]
    if mutation == "cross_speaker":
        group["speaker"] = "B"
    elif mutation == "duplicate_coverage":
        group["source_segment_ids"] = ["SRC_1", "SRC_1"]
    elif mutation == "merge_reason":
        group["merge_reason"] = ""
    elif mutation == "overlap":
        plan["segments"][1]["start_sec"] = 2.5
    elif mutation == "reference_speaker":
        group["reference"].update(source_segment_ids=["SRC_3"], start_sec=3.5, end_sec=5.5)
    elif mutation == "reference_padding":
        group["reference"]["end_sec"] = 5.0
    elif mutation == "source_text":
        group["source_text"] = "Invented text"
    elif mutation == "unknown_id":
        group["source_segment_ids"] = ["SRC_UNKNOWN"]
    elif mutation == "source_language":
        plan["source_language"] = "auto"
    elif mutation == "nonfinite":
        group["start_sec"] = float("nan")
    elif mutation == "boolean_interval":
        group["start_sec"] = True
    path.write_text(json.dumps(plan))
    with pytest.raises(client.DubbingError):
        validate_plan(journey["root"], path)


@pytest.mark.parametrize("changed", ["original", "local_source", "vocals", "background", "vad", "transcript"])
async def test_changed_artifact_bytes_are_rejected(journey, changed):
    """GIVEN changed exact local bytes WHEN validated THEN the lineage fails."""
    path, _, _ = await prepare_and_plan(journey)
    targets = {"original": journey["source"], "local_source": journey["root"] / "work/source/source.mp4",
               "vocals": journey["root"] / "work/source/vocals.wav",
               "background": journey["root"] / "work/source/no_vocals.wav",
               "vad": journey["root"] / "analysis/vad.json", "transcript": journey["root"] / "analysis/transcript.json"}
    with targets[changed].open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(client.DubbingError):
        validate_plan(journey["root"], path)


async def test_unresolved_source_blocks_render(journey):
    """GIVEN unresolved source identity WHEN plan is checked THEN rendering blocks."""
    path, plan, transcript = await prepare_and_plan(journey)
    transcript["unresolved_issues"] = ["Speaker B uncertain"]
    client.write_json(journey["root"] / "analysis/transcript.json", transcript)
    plan["transcript_sha256"] = artifact(journey["root"] / "analysis/transcript.json")["sha256"]
    client.write_json(path, plan)
    with pytest.raises(client.DubbingError):
        validate_plan(journey["root"], path)


async def test_timing_failure_retains_candidates_and_failure(journey):
    """GIVEN three overlong results WHEN rendered THEN timing stays explicitly failed."""
    path, _, _ = await prepare_and_plan(journey)
    journey["controls"]["tts_seconds"] = 10.0
    with pytest.raises(client.DubbingError, match="timing_failed"):
        await workflow.render_project(str(journey["root"]), str(path), "include")
    assert len([url for url, _ in journey["calls"] if url.endswith("/tts")]) == 3
    failures = list(journey["root"].glob("renders/*/render_failure_*.json"))
    assert len(failures) == 1
    value = json.loads(failures[0].read_bytes())
    assert value["timing"] == "FAIL" and value["listening"] == "UNRESOLVED"
    assert not (journey["root"] / "full/current.json").exists()
    assert len(list(journey["root"].glob("work/voices/*/*/candidate-*.wav"))) == 3


@pytest.mark.parametrize("control", ["decode_fail", "extra_stream", "output_duration"])
async def test_technical_failure_is_not_delivery(journey, control):
    """GIVEN decode/stream/duration failure WHEN rendered THEN preserve failed QA."""
    path, _, _ = await prepare_and_plan(journey)
    journey["controls"][control] = 9.0 if control == "output_duration" else True
    with pytest.raises((client.DubbingError, RuntimeError)):
        await workflow.render_project(str(journey["root"]), str(path), "include")
    assert list(journey["root"].glob("renders/*/render_failure_*.json"))
    assert not (journey["root"] / "full/current.json").exists()


async def test_unready_service_stops_before_source_and_process(journey, monkeypatch):
    """GIVEN loading service WHEN prepared THEN only terminal readiness is evidence."""
    async def unready():
        return {"state": "unready", "terminal": True, "model_loaded": False}
    monkeypatch.setattr(client, "health", unready)
    result = await workflow.prepare("/does/not/exist", str(journey["root"]), "en", "nl", "0" * 64)
    assert result["status"] == "readiness_terminal"
    assert not journey["commands"] and not journey["calls"]


async def test_pcm_size_admission_precedes_extraction(journey):
    """GIVEN an oversized decoded PCM projection WHEN prepared THEN no extraction runs."""
    journey["controls"]["source_duration"] = 1600.0
    with pytest.raises(client.DubbingError, match="pcm_bound"):
        await workflow.prepare(str(journey["source"]), str(journey["root"]), "en", "nl",
                               artifact(journey["source"])["sha256"])
    assert all("ffprobe" in argv[0] for argv in journey["commands"])
    assert all(url.endswith("/health") for url, _ in journey["calls"])


async def test_requested_analysis_target_and_style_are_retained(journey):
    """GIVEN an analysis-only request WHEN prepared THEN retain its stop and exact style."""
    result = await workflow.prepare(str(journey["source"]), str(journey["root"]), "en", "nl",
                                    artifact(journey["source"])["sha256"], "analysis_only", "Calm, precise delivery")
    assert result["target"] == "analysis_only" and result["style_brief"] == "Calm, precise delivery"
    assert result["next_action"] == "review_source_transcript_and_stop"
    assert not any(url.endswith("/tts") for url, _ in journey["calls"])


async def test_failed_listening_checks_remain_visible(journey):
    """GIVEN a content-bound failed review WHEN validated THEN never fabricate PASS."""
    path, _, _ = await prepare_and_plan(journey)
    result = await workflow.render_project(str(journey["root"]), str(path), "omit")
    review_path = Path(result["render_report"]["path"]).parent / "listening_review.json"
    client.write_json(review_path, {"schema_version": "vrm/video-dubbing-listening/v1",
                                   "output_sha256": result["output"]["sha256"],
                                   "plan_sha256": artifact(path)["sha256"], "reviewer": "synthetic-test-review",
                                   "segment_checks": {"DUB_0001": {"timing": "FAIL"}}, "issues": ["Timing unresolved"]})
    checked = await workflow.validate_delivery(str(journey["root"]))
    assert checked["valid"] is False
    assert checked["listening"]["segments"]["DUB_0001"]["timing"] == "FAIL"
    assert checked["listening"]["segments"]["DUB_0002"]["mix"] == "UNRESOLVED"


async def test_supplied_review_does_not_qualify_native_service(journey):
    """GIVEN synthetic supplied PASS labels WHEN joined THEN operational gates stay open."""
    path, _, _ = await prepare_and_plan(journey)
    result = await workflow.render_project(str(journey["root"]), str(path), "include")
    checks = {segment_id: {key: "PASS" for key in
                          ("translation", "timing", "voice_reference", "natural_delivery", "mix")}
              for segment_id in ("DUB_0001", "DUB_0002")}
    client.write_json(Path(result["render_report"]["path"]).parent / "listening_review.json",
                      {"schema_version": "vrm/video-dubbing-listening/v1",
                       "output_sha256": result["output"]["sha256"],
                       "plan_sha256": artifact(path)["sha256"], "reviewer": "synthetic fixture",
                       "segment_checks": checks, "issues": []})
    checked = await workflow.validate_delivery(str(journey["root"]))
    assert checked["valid"] is True and checked["listening"]["evidence"] == "supplied_review"
    assert checked["feature_acceptance"] == checked["service_acceptance"] == checked["native_acceptance"] == "UNQUALIFIED"


async def test_delivery_detects_output_and_process_receipt_tampering(journey):
    """GIVEN tampered local output WHEN revalidated THEN fail exact output custody."""
    path, _, _ = await prepare_and_plan(journey)
    result = await workflow.render_project(str(journey["root"]), str(path), "include")
    with Path(result["output"]["path"]).open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(client.DubbingError):
        await workflow.validate_delivery(str(journey["root"]))


@pytest.mark.parametrize("url,local", [("http://service.example", False),
                                     ("https://user:secret@service.example", False),
                                     ("http://localhost:9000", True),
                                     ("https://127.0.0.1", False),
                                     ("https://service.example/path", False),
                                     ("https://service.example?secret=x", False)])
def test_origin_policy(url, local):
    """GIVEN an unsafe authority WHEN configured THEN reject before transmission."""
    with pytest.raises(ValueError):
        DubbingService(base_url=url, local=local)


async def test_tool_schema_errors_and_terminal_readiness(journey, monkeypatch):
    """GIVEN tool entry points WHEN discovered/called THEN conventions and errors hold."""
    from video_research_mcp.tools import video_dubbing as tools
    listed = await tools.video_dubbing_server.list_tools()
    assert len(listed) == 9
    assert all(tool.annotations is not None for tool in listed)
    value = await tools.validate_video_translation_plan(str(journey["root"]), str(journey["root"] / "missing.json"))
    assert "error" in value and "category" in value
    assert "synthetic-test-token" not in json.dumps(value)


async def test_standalone_synthesis_tool_is_executable(journey):
    """GIVEN the eighth mapped source tool WHEN called THEN retain local audio/uncertainty."""
    from video_research_mcp.tools.video_dubbing import synthesize_dubbing_speech
    reference = journey["source"].parent / "reference.wav"
    reference.write_bytes(wav_bytes())
    result = await synthesize_dubbing_speech("Hallo vriend", str(reference),
                                            str(journey["source"].parent / "standalone.wav"))
    assert result["listening"] == "UNRESOLVED" and result["voice_quality"] == "UNQUALIFIED"
    assert Path(result["path"]).read_bytes() == wav_bytes()


def test_inclusive_full_analysis_and_reconciled_long_windows():
    """GIVEN the analysis routing boundary WHEN covered THEN preserve both workflows."""
    _analysis_windows([Interval(start_sec=0, end_sec=600)], 600)
    _analysis_windows([Interval(start_sec=0, end_sec=400),
                       Interval(start_sec=395, end_sec=800)], 800)
    with pytest.raises(client.DubbingError):
        _analysis_windows([Interval(start_sec=0, end_sec=300),
                           Interval(start_sec=300, end_sec=600)], 600)
    with pytest.raises(client.DubbingError):
        _analysis_windows([Interval(start_sec=0, end_sec=390),
                           Interval(start_sec=395, end_sec=800)], 800)


async def test_descriptor_entrypoint_and_source_tools_resolve():
    """GIVEN the descriptor WHEN loaded THEN its real entry point exposes mapped tools."""
    import importlib
    repo = Path(__file__).resolve().parents[1]
    descriptor = json.loads((repo / "integrations/qwen/omni-chatcut.json").read_bytes())
    module, name = descriptor["entry_point"].split(":")
    server = getattr(importlib.import_module(module), name)
    tools = await server.list_tools()
    assert set(descriptor["source_tool_mappings"]) <= {tool.name for tool in tools}
    assert descriptor["first_party_state_tool"] in {tool.name for tool in tools}
