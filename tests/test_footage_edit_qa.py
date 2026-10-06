"""Strict measurement, complete population and declared-timeline parser controls."""

import copy

import pytest

from tests.test_footage_edit_native import hash_rows, video_info
from video_research_mcp import footage_edit_qa as qa
from video_research_mcp.footage_edit_timeline import beat_report, scene_frames
from video_research_mcp.models.footage_edit import PrepareRequest


def plan(beats=None):
    """Keep explicit source/timeline intent fixed while testing declared beat choices."""
    return PrepareRequest.model_validate({"action": "prepare", "brief": "Fixed parser control", "fps": 10,
        "beats": beats or {"mode": "none"}, "scenes": [
            {"scene_id": "A", "file_path": "/fixture/a.mp4", "expected_source_sha256": "a" * 64,
             "start_seconds": 0, "end_seconds": .2, "timeline_start_seconds": 0},
            {"scene_id": "B", "file_path": "/fixture/b.mp4", "expected_source_sha256": "b" * 64,
             "start_seconds": 0, "end_seconds": .2, "timeline_start_seconds": .2}]})


@pytest.mark.parametrize("wire", [b"", b"#hash: MD5\n#tb 0: 1/10\n", hash_rows([0]),
    hash_rows([0, 100]).replace(b"#tb 0: 1/1000", b"#tb 0: 0/1"),
    hash_rows([100, 0]), hash_rows([0, 100]).replace(b"576,", b"0,"),
    hash_rows([0, 100]) + b"extra malformed row\n"])
def test_framehash_absence_malformed_or_incomplete_refuses(wire):
    """A decoder count or a nominal success status is insufficient without complete hashes."""
    with pytest.raises((ValueError, ZeroDivisionError)):
        qa.frame_hashes(wire, 2)


def test_education_population_requires_explicit_ceiling_and_complete_hashes():
    """Keep footage at256 frames while admitting the concrete30s education population."""
    wire = hash_rows(list(range(360)))
    with pytest.raises(ValueError, match="complete population"):
        qa.frame_hashes(wire, 360)
    assert len(qa.frame_hashes(wire, 360, max_frames=360)) == 360
    for count in (359, 361):
        with pytest.raises(ValueError, match="complete population"):
            qa.frame_hashes(hash_rows(list(range(count))), 360, max_frames=360)
    with pytest.raises(ValueError, match="complete population"):
        qa.frame_hashes(hash_rows(list(range(361))), 361, max_frames=360)


async def test_full_review_carries_explicit_education_frame_ceiling():
    """Inspect all360 native hash rows through the complete technical-review caller."""
    times = [n / 12 for n in range(360)]
    measured = {"output": {"frame_count": 360, "decoded_frame_seconds": times,
                           "duration_seconds": 30, "width": 640, "height": 360,
                           "video_codec": "h264"}, "audio": None}
    timeline = {"frames": [{"timeline_seconds": t} for t in times],
                "duration_seconds": 30, "fps": 12, "dimensions": [640, 360]}

    class Work:
        def __init__(self):
            self.outputs = iter([(b"frame=360\nprogress=end\n", b""),
                                 (hash_rows(list(range(360))), b"")])

        async def run(self, command):
            return next(self.outputs)

    result = await qa.full_review("unused.mp4", Work(), measured, timeline, False,
                                  max_frames=360)
    assert result["full_decode"] and len(result["decoded_frames"]) == 360


@pytest.mark.parametrize("wire", [b"", b"frame=2\nprogress=continue\n", b"frame=1\nprogress=end\n",
                                  b"progress=end\n", b"frame=2\nprogress=end\nextra"])
def test_full_decoder_progress_must_be_terminal_and_complete(wire):
    """No black spans is accepted only with an actual full completed decoder receipt."""
    with pytest.raises(ValueError):
        qa.progress(wire, 2)


@pytest.mark.parametrize("wire", [
    b"[blackdetect @ 0xabc] black_start:0 black_end:0.1 black_duration:0.1\n",
    b"[blackdetect @ 0xabc] black_start:1.1 black_end:1.3 black_duration:0.2\n",
    b"[blackdetect @ 0xabc] black_start:1.9 black_end:2 black_duration:0.1\n",
    b"[blackdetect @ 0xabc] black_start:bad\n",
])
def test_black_span_anywhere_including_head_tail_refuses(wire):
    """The fixed gate has no interior-only exception or malformed-record success path."""
    with pytest.raises(ValueError):
        qa.black_summary(wire)


def test_complete_nonblack_decode_preserves_measurement_identity():
    """No span is an observation under fixed thresholds rather than a visual-quality proof."""
    qa.progress(b"frame=2\nprogress=end\n", 2)
    result = qa.black_summary(b"completed decoder metadata\n")
    assert result["spans"] == [] and result["head_tail_grace_seconds"] == 0
    assert result["minimum_seconds"] == .1 and len(result["stderr_sha256"]) == 64


@pytest.mark.parametrize("i,lra,peak", [("-25", "0", "-6"), ("-9", "0", "-6"),
    ("-18", "0", "-1"), ("nan", "0", "-6"), ("-18", "inf", "-6"), ("-18", "0", "-inf"),
    ("-18", "-1", "-6")])
def test_loudness_is_a_finite_hard_gate(i, lra, peak):
    """Undefined, too hot, too quiet or malformed measurements do not deliver audio."""
    with pytest.raises(ValueError):
        qa.loudness_gate(f" Summary:\n I: {i} LUFS\n LRA: {lra} LU\n Peak: {peak} dBFS\n".encode())


@pytest.mark.parametrize("wire", [b"", b" I: -18 LUFS\n LRA: 0 LU\n Peak: -6 dBFS\n",
    b" Summary:\n I: -18 LUFS\n LRA: 0 LU\n", b" Summary:\n I: -18 LUFS\n I: -18 LUFS\n LRA: 0 LU\n Peak: -6 dBFS\n"])
def test_missing_or_duplicate_terminal_loudness_fields_refuse(wire):
    """Public acceptance never infers measurement success from a process exit alone."""
    with pytest.raises(ValueError):
        qa.loudness_gate(wire)


def test_loudness_exact_limits_keep_display_and_standards_caveat():
    """Inclusive physical observations use the existing one-decimal terminal summary contract."""
    result = qa.loudness_gate(b" Summary:\n I: -24 LUFS\n LRA: 0 LU\n Peak: -1.5 dBFS\n")
    assert result["display_precision_decimals"] == 1
    assert result["standards_conformance_verified"] is False


@pytest.mark.parametrize("wire", [b"", b"frame:0 pts:0 pts_time:0\nlavfi.signalstats.YAVG=80\n",
    b"frame:0 pts:0 pts_time:0\nlavfi.signalstats.YMIN=0\nlavfi.signalstats.YAVG=nan\nlavfi.signalstats.YMAX=200\nlavfi.signalstats.SATAVG=20\n"])
def test_signal_missing_incomplete_nonfinite_refuses(wire):
    """Corrections require actual finite before/after fields covering every selected frame."""
    with pytest.raises(ValueError):
        qa.signal_summary(wire, 2)


def test_declared_grid_distance_and_explicit_offbeat_are_not_beat_detection():
    """Declared BPM is intent; a mismatch fails unless an explicit offbeat choice is made."""
    matched = plan({"mode": "declared", "bpm": 300, "origin_seconds": 0})
    assert beat_report(matched)["cuts"][0]["frame_distance"] == pytest.approx(0)
    mismatch = plan({"mode": "declared", "bpm": 120, "origin_seconds": 0, "tolerance_frames": 1.5})
    with pytest.raises(ValueError, match="beat-grid"):
        beat_report(mismatch)
    mismatch.beats.mode = "offbeat"
    result = beat_report(mismatch)
    assert result["cuts"][0]["frame_distance"] == pytest.approx(2)
    assert result["measured_beat_detection"] is False and result["music_added"] is False


def test_missing_source_frames_are_not_replaced_by_requested_times():
    """Every original PTS must exist and agree with the declared uniform timeline."""
    scene = plan().scenes[0]
    frames = [{"original_pts": 0, "time_base": "1/1000", "actual_seconds": 0},
              {"original_pts": 110, "time_base": "1/1000", "actual_seconds": .11}]
    with pytest.raises(ValueError, match="resampling"):
        scene_frames(scene, frames, qa.frame_hashes(hash_rows([0, 110]), 2), 10)
    with pytest.raises(ValueError, match="population"):
        scene_frames(scene, frames[:1], qa.frame_hashes(hash_rows([0]), 1), 10)


@pytest.mark.parametrize("change", ["count", "clock", "duration", "grid", "codec", "audio"])
async def test_final_structural_clock_population_refuses_before_measurement(change):
    """Complete source-to-shot clock, shape and audio commitments precede technical promotion."""
    info = video_info([0, 100], .2)
    measured = {"output": {"frame_count": 2, "decoded_frame_seconds": [0, .1], "duration_seconds": .2,
                           "width": 16, "height": 12, "video_codec": "h264"}, "audio": {"included": True}}
    timeline = {"frames": [{"timeline_seconds": 0}, {"timeline_seconds": .1}], "duration_seconds": .2,
                "fps": 10, "dimensions": [info["streams"][0]["width"], 12]}
    measured = copy.deepcopy(measured)
    if change == "count":
        measured["output"]["frame_count"] = 1
    elif change == "clock":
        measured["output"]["decoded_frame_seconds"][1] = .1001
    elif change == "duration":
        measured["output"]["duration_seconds"] = .4
    elif change == "grid":
        measured["output"]["width"] = 15
    elif change == "codec":
        measured["output"]["video_codec"] = "other"
    else:
        measured["audio"] = None
    with pytest.raises(ValueError):
        await qa.full_review("unused.mp4", None, measured, timeline, True)


def test_default_plan_roundtrip_keeps_exact_manifest_commitment():
    """Default FPS must serialize identically when reopening the exact prepared plan."""
    from video_research_mcp.image_manifest import json_digest

    data = plan().model_dump()
    data.pop("fps")
    data["scenes"] = [data["scenes"][0]]
    data["scenes"][0]["end_seconds"] = .5
    original = PrepareRequest.model_validate(data)
    restored = PrepareRequest.model_validate(original.model_dump())
    assert json_digest(original.model_dump()) == json_digest(restored.model_dump())
