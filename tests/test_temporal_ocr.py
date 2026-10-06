"""Temporal track boundaries over shared authored native/receipt fixtures."""

from pathlib import Path

import pytest

from tests.test_temporal_ocr_mcp import request, set_frames, transcript_receipt
from tests.test_temporal_ocr_mcp import scene_fixture as scene_fixture
from video_research_mcp import image_ocr
from video_research_mcp.temporal_ocr import build_ocr_timeline


async def test_changed_text_retains_both_states_actual_clock_and_single_inverse(scene_fixture):
    """Identical backgrounds and a changed error retain actual PTS and original ROI corners."""
    from video_research_mcp.image_manifest import read_manifest

    result = await build_ocr_timeline(request(scene_fixture))
    assert result["status"] == "complete" and result["source_verified"]
    first, second = result["points"]
    assert [p["ocr"]["text"] for p in result["points"]] == ["error A", "error B"]
    assert [
        p["ocr"]["preparation"]["frame"]["actual_seconds"] for p in result["points"]
    ] == pytest.approx([0.2, 0.8])
    assert first["ocr"]["preparation"]["frame"]["original_pts"] == 7200
    assert second["text_changed"] is True
    observation = first["ocr"]["observations"][0]
    assert observation["prepared_points"] == [[40, 20], [120, 20], [120, 60], [40, 60]]
    assert observation["stored_points"] == [[40, 20], [80, 20], [80, 40], [40, 40]]
    restored = await read_manifest(
        first["ocr"]["manifest"]["path"], first["ocr"]["manifest"]["sha256"]
    )
    assert restored["observations"][0]["stored_points"] == observation["stored_points"]
    assert result["coverage"]["watched_intervals"] == []
    assert result["provenance"]["continuous_observation"] is False
    assert result["limits"]["provider_calls"] == 0


@pytest.mark.parametrize(
    "texts,expected",
    [
        (["1", "2", "3"], 0),
        (["3", "2", "4"], 1),
        (["-1", "-2", "0"], 1),
        (
            [
                "9007199254740993.0000000000000001",
                "9007199254740993.0000000000000000",
                "9007199254740994",
            ],
            1,
        ),
    ],
)
async def test_exact_numeric_track_increasing_and_fixed_reversal(scene_fixture, texts, expected):
    set_frames(scene_fixture, texts, confidence=None)
    result = await build_ocr_timeline(
        request(scene_fixture, times_seconds=[0.1, 0.6, 1.1], track_numbers=True)
    )
    assert len(result["numeric_candidates"]) == expected
    if expected:
        candidate = result["numeric_candidates"][0]
        assert candidate["point_index"] == 1 and candidate["actual_seconds"] == pytest.approx(0.8)
        assert candidate["uncertain"] is True and candidate["confidence"] is None
        assert candidate["source_sha256"] == result["source"]["sha256"]
        assert (
            candidate["raw_backend_sha256"]
            == result["points"][1]["ocr"]["raw_backend_artifact"]["sha256"]
        )
        assert candidate["basis"] == "ocr_numeric_heuristic"


@pytest.mark.parametrize(
    "middle,status",
    [
        ([], "missing"),
        (["4", "5"], "ambiguous"),
        ("1e9999", "unsupported"),
        ("9" * 129, "unsupported"),
        ("NaN", "unsupported"),
        ("1,000", "unsupported"),
    ],
)
async def test_missing_ambiguous_and_unsupported_numbers_do_not_bridge(
    scene_fixture, middle, status
):
    set_frames(scene_fixture, ["9", middle, "1"])
    result = await build_ocr_timeline(
        request(scene_fixture, times_seconds=[0.1, 0.6, 1.1], track_numbers=True)
    )
    assert result["points"][1]["number"]["status"] == status
    assert result["numeric_candidates"] == []


async def test_nontracking_preserves_text_without_numeric_semantics(scene_fixture):
    set_frames(scene_fixture, ["3", "2"])
    result = await build_ocr_timeline(request(scene_fixture))
    assert result["numeric_candidates"] == [] and result["points"][0]["number"] is None


async def test_same_decoded_frame_is_not_a_temporal_transition(scene_fixture):
    result = await build_ocr_timeline(request(scene_fixture, times_seconds=[0.01, 0.02]))
    assert len(result["points"]) == 2
    assert result["points"][1]["text_changed"] is None
    assert result["coverage"]["sampled_points"] == pytest.approx([0.2, 0.2])


async def test_unavailable_engine_stops_remaining_dispatch_and_retains_statuses(scene_fixture):
    scene_fixture["failures"][0] = ImportError("Local OCR requires optional installed runtime")
    result = await build_ocr_timeline(request(scene_fixture, times_seconds=[0.1, 0.6, 1.1]))
    assert [p["status"] for p in result["points"]] == ["failed", "not_run", "not_run"]
    assert result["points"][0]["error"]["category"] == "DEPENDENCY_MISSING"
    assert scene_fixture["ocr_calls"] == [0]
    assert list((scene_fixture["source"].parent / "cache/media/views").iterdir()) == []


async def test_failed_point_keeps_prior_and_later_evidence_without_bridging(scene_fixture):
    set_frames(scene_fixture, ["9", "8", "1"])
    scene_fixture["failures"][1] = ValueError("Owned malformed native OCR payload")
    result = await build_ocr_timeline(
        request(scene_fixture, times_seconds=[0.1, 0.6, 1.1], track_numbers=True)
    )
    assert result["status"] == "partial"
    assert [p["status"] for p in result["points"]] == ["complete", "failed", "complete"]
    assert result["numeric_candidates"] == [] and result["points"][2]["text_changed"] is None
    assert Path(result["points"][0]["ocr"]["raw_backend_artifact"]["path"]).exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"times_seconds": []},
        {"times_seconds": list(range(7))},
        {"times_seconds": [0.2, 0.2]},
        {"times_seconds": [0.3, 0.1]},
        {"times_seconds": [True]},
        {"times_seconds": [float("nan")]},
        {"times_seconds": [-1]},
        {"engine": "cloud"},
        {"languages": ["--flag"]},
        {"track_numbers": 1},
        {"max_pixels": True},
        {"max_pixels": 1_000_001},
        {"detect_barcodes": True},
        {"unknown": 1},
    ],
)
def test_request_refuses_invalid_controls(scene_fixture, changes):
    with pytest.raises(ValueError):
        request(scene_fixture, **changes)
    assert scene_fixture["commands"] == []


@pytest.mark.parametrize("change", ["transcribe", "source", "digest"])
def test_speech_only_allows_same_source_receipt_readback(scene_fixture, change):
    speech = transcript_receipt(scene_fixture)
    if change == "transcribe":
        speech.update(
            action="transcribe",
            expected_receipt_sha256=None,
            backend="gemini",
            authorize_submission=True,
        )
    elif change == "source":
        speech["file_path"] = str(scene_fixture["source"].with_name("other.mp4"))
    else:
        speech["expected_source_sha256"] = "b" * 64
    with pytest.raises(ValueError):
        request(scene_fixture, transcript=speech)


@pytest.mark.parametrize("inferred", [False, True])
async def test_verified_speech_retains_caption_vs_inferred_word_speaker_provenance(
    scene_fixture, inferred
):
    speech = transcript_receipt(scene_fixture, inferred=inferred)
    result = await build_ocr_timeline(request(scene_fixture, transcript=speech))
    assert result["speech"]["status"] == "verified_readback"
    transcript = result["speech"]["transcript"]
    assert transcript["outcome"] == ("inferred" if inferred else "captions")
    assert transcript["provenance"]["speech_accuracy_verified"] is False
    assert transcript["segments"][0]["words"][0]["start_seconds"] == 0.15
    assert (
        "inferred" in transcript["provenance"]["word_status"]
        if inferred
        else "assertion" in transcript["provenance"]["word_status"]
    )
    assert result["numeric_candidates"] == []


@pytest.mark.parametrize("target", ["receipt.json", "transcript-result.json"])
async def test_changed_transcript_bytes_cannot_enter_speech_channel(scene_fixture, target):
    speech = transcript_receipt(scene_fixture)
    path = Path(speech["output_directory"]) / target
    path.write_bytes(path.read_bytes() + b"changed")
    result = await build_ocr_timeline(request(scene_fixture, transcript=speech))
    assert result["status"] == "partial" and result["speech"]["status"] == "failed"
    assert result["speech"]["transcript"] is None


async def test_stale_original_fails_before_any_native_dispatch(scene_fixture):
    req = request(scene_fixture)
    scene_fixture["source"].write_bytes(b"changed source")
    result = await build_ocr_timeline(req)
    assert result["status"] == "failed" and not result["source_verified"]
    assert all(p["ocr"] is None for p in result["points"])
    assert scene_fixture["commands"] == []


@pytest.mark.parametrize("kind", ["symlink", "escape", "url"])
async def test_source_policy_refusals_never_dispatch(scene_fixture, kind):
    source = scene_fixture["source"]
    if kind == "symlink":
        linked = source.with_name("linked.mp4")
        linked.symlink_to(source)
        path = str(linked)
    elif kind == "escape":
        path = str(source.parent.parent / "escaped.mp4")
    else:
        path = "https://example.invalid/video.mp4"
    result = await build_ocr_timeline(request(scene_fixture, file_path=path))
    assert result["status"] == "failed" and scene_fixture["commands"] == []


async def test_unverified_native_clock_is_failure_not_requested_time(scene_fixture):
    scene_fixture["bad_pts"] = 79999
    result = await build_ocr_timeline(request(scene_fixture))
    assert result["status"] == "failed"
    assert all(p["ocr"] is None for p in result["points"])
    assert result["coverage"]["sampled_points"] == []


async def test_aggregate_reservation_stops_before_exceeding_retained_byte_budget(scene_fixture):
    speech = transcript_receipt(scene_fixture, padding=4 * 1024 * 1024)
    result = await build_ocr_timeline(request(scene_fixture, transcript=speech))
    assert result["status"] == "partial" and result["speech"]["status"] == "verified_readback"
    assert all(
        p["status"] == "not_run" and p["reason"] == "artifact_budget" for p in result["points"]
    )
    assert scene_fixture["ocr_calls"] == []
    assert result["artifact_bytes"] <= 8 * 1024 * 1024


async def test_one_timeline_deadline_retains_first_point_and_skips_remaining(
    scene_fixture, monkeypatch
):
    from video_research_mcp import temporal_ocr

    monkeypatch.setattr(temporal_ocr, "DEADLINE_SECONDS", 0.15)
    scene_fixture["delay_index"] = 1
    result = await build_ocr_timeline(request(scene_fixture, times_seconds=[0.1, 0.6, 1.1]))
    assert result["status"] == "partial"
    assert [p["status"] for p in result["points"]] == ["complete", "failed", "not_run"]
    assert result["points"][2]["reason"] == "deadline"
    assert scene_fixture["ocr_calls"] == [0, 1]
    assert Path(result["points"][0]["ocr"]["manifest"]["path"]).exists()


async def test_changed_original_retains_failed_partial_evidence(scene_fixture):
    scene_fixture["mutate_index"] = 1
    result = await build_ocr_timeline(request(scene_fixture))
    assert result["status"] == "failed" and not result["source_verified"]
    assert [p["status"] for p in result["points"]] == ["complete", "failed"]
    assert result["error"]["category"] == "SCHEMA_VALIDATION_FAILED"
    assert Path(result["points"][0]["ocr"]["manifest"]["path"]).exists()


async def test_tesseract_route_reuses_exact_tsv_and_unknown_line_confidence(
    scene_fixture, monkeypatch
):
    set_frames(scene_fixture, ["9", "8"])
    calls = []

    async def tesseract(command, timeout):
        calls.append(command)
        row = scene_fixture["current"][1]
        header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        return (
            header + "5\t1\t1\t1\t1\t1\t40\t20\t80\t40\t95\t" + row["text"] + "\n"
        ).encode(), b""

    monkeypatch.setattr(image_ocr, "run_media_process", tesseract)
    result = await build_ocr_timeline(
        request(scene_fixture, engine="tesseract", languages=["eng"], track_numbers=True)
    )
    assert len(calls) == 2 and scene_fixture["ocr_calls"] == []
    assert all(command[-3:] == ["-l", "eng", "tsv"] for command in calls)
    assert result["numeric_candidates"][0]["confidence"] is None
    assert result["points"][0]["ocr"]["observations"][0]["stored_points"] == [
        [40, 20],
        [80, 20],
        [80, 40],
        [40, 40],
    ]


async def test_mutated_request_instance_is_revalidated_before_dispatch(scene_fixture):
    req = request(scene_fixture)
    req.times_seconds[:] = [0.1, 0.1]
    with pytest.raises(ValueError, match="strictly increasing"):
        await build_ocr_timeline(req)
    assert scene_fixture["commands"] == []


async def test_missing_ocr_does_not_assert_text_transition(scene_fixture):
    set_frames(scene_fixture, ["error A", []])
    result = await build_ocr_timeline(request(scene_fixture))
    assert result["points"][1]["ocr"]["observations"] == []
    assert result["points"][1]["text_changed"] is None


async def test_prior_raw_artifact_change_blocks_complete_timeline(scene_fixture):
    def change_prior(index):
        if index == 1:
            root = scene_fixture["source"].parent / "cache/media/views"
            next(root.glob("*/ocr-raw.json")).write_bytes(b"changed prior OCR")

    scene_fixture["ocr_hook"] = change_prior
    result = await build_ocr_timeline(request(scene_fixture))
    assert result["status"] == "failed"
    assert result["error"]["category"] == "SCHEMA_VALIDATION_FAILED"


async def test_speech_artifact_change_during_ocr_blocks_complete_readback(scene_fixture):
    speech = transcript_receipt(scene_fixture)

    def change_speech(index):
        if index == 1:
            (Path(speech["output_directory"]) / "transcript-result.json").write_bytes(
                b"changed transcript"
            )

    scene_fixture["ocr_hook"] = change_speech
    result = await build_ocr_timeline(request(scene_fixture, transcript=speech))
    assert result["status"] == "failed" and result["speech"]["status"] == "failed"


async def test_caption_original_change_during_ocr_invalidates_verified_speech(scene_fixture):
    speech = transcript_receipt(scene_fixture, caption=True)

    def change_caption(index):
        if index == 1:
            (scene_fixture["source"].parent / "original-caption.srt").write_bytes(
                b"changed caption"
            )

    scene_fixture["ocr_hook"] = change_caption
    result = await build_ocr_timeline(request(scene_fixture, transcript=speech))
    assert result["status"] == "failed" and result["speech"]["status"] == "failed"


async def test_partial_readback_and_empty_artifact_remain_partial_and_exact(scene_fixture):
    speech = transcript_receipt(scene_fixture, partial=True, empty=True)
    result = await build_ocr_timeline(request(scene_fixture, transcript=speech))
    assert result["status"] == "partial"
    assert result["speech"]["transcript"]["status"] == "partial"
    assert any(record["bytes"] == 0 for record in result["artifacts"])


@pytest.mark.parametrize("change", ["origin", "time_base", "request"])
async def test_typed_clock_refuses_changed_source_clock_commitments(scene_fixture, change):
    from video_research_mcp.models.video_evidence import TimelineOCR

    result = await build_ocr_timeline(request(scene_fixture))
    data = result["points"][0]["ocr"]
    if change == "origin":
        data["source"]["container_start_seconds"] += 0.01
    elif change == "time_base":
        data["preparation"]["frame"]["time_base"] = "1/999"
    else:
        data["preparation"]["frame"]["requested_seconds"] = 0.3
    with pytest.raises(ValueError, match="original source PTS"):
        TimelineOCR.model_validate(data)


async def test_cleanup_failure_preserves_primary_clock_refusal(scene_fixture, monkeypatch):
    """Cleanup refusal is separate from the original rejected clock."""
    from video_research_mcp import temporal_ocr

    def reject_clock(*args):
        raise ValueError("primary clock refusal")

    def refuse_cleanup(*args):
        raise PermissionError("cleanup parent replaced")

    monkeypatch.setattr(temporal_ocr, "_clock", reject_clock)
    monkeypatch.setattr(temporal_ocr, "_discard_views", refuse_cleanup)
    result = await build_ocr_timeline(request(scene_fixture, times_seconds=[0.1]))
    point = result["points"][0]
    assert point["error"]["category"] == "SCHEMA_VALIDATION_FAILED"
    assert point["error"]["error"] == "primary clock refusal"
    assert point["cleanup_error"]["category"] == "PERMISSION_DENIED"
    assert point["cleanup_error"]["error"] == "cleanup parent replaced"


async def test_cleanup_failure_does_not_swallow_deadline_cancel(scene_fixture, monkeypatch):
    """A cleanup refusal cannot let another point run after the single deadline."""
    import asyncio
    from types import SimpleNamespace

    from video_research_mcp import temporal_ocr

    deadlines, expired_at_check = [], []

    def timeline_deadline(delay):
        deadlines.append(asyncio.timeout(delay))
        return deadlines[-1]

    async def deadline_during_artifact_check(records):
        # Expire the one timeline deadline exactly here, not after load-dependent wall time.
        expired_at_check.append(deadlines[0].expired())
        deadlines[0].reschedule(asyncio.get_running_loop().time())
        await asyncio.sleep(1)

    def refuse_cleanup(*args):
        raise PermissionError("cleanup parent replaced")

    monkeypatch.setattr(temporal_ocr, "asyncio", SimpleNamespace(timeout=timeline_deadline))
    monkeypatch.setattr(temporal_ocr, "_verify_artifacts", deadline_during_artifact_check)
    monkeypatch.setattr(temporal_ocr, "_discard_views", refuse_cleanup)
    result = await build_ocr_timeline(request(scene_fixture, times_seconds=[0.1, 0.6]))
    assert len(deadlines) == 1 and expired_at_check == [False]
    assert scene_fixture["ocr_calls"] == [0]
    assert [point["status"] for point in result["points"]] == ["failed", "not_run"]
    assert result["points"][1]["reason"] == "deadline"
    assert result["error"]["category"] == "NETWORK_ERROR"
    assert result["points"][0]["cleanup_error"]["category"] == "PERMISSION_DENIED"
