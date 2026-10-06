"""Mock-only regressions for fitted speech duration and process cache fencing."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from video_research_mcp import dubbing_client as client
from video_research_mcp import dubbing_render as render
from tests.test_dubbing_client import wav_bytes


@pytest.fixture
def voice(tmp_path, monkeypatch, clean_config):
    """Create real PCM fixtures and replace only the external process boundary."""
    from video_research_mcp.config import get_config

    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    get_config().local_file_access_root = str(tmp_path)
    monkeypatch.setattr(render, "binary", lambda name: "/mock/" + name)
    raw, output, reference = (tmp_path / name for name in ("raw.wav", "fit.wav", "reference.wav"))
    raw.write_bytes(wav_bytes(0.9, rate=24000, channels=1))
    reference.write_bytes(wav_bytes(1.6))
    state = {"output_frames": 62400}

    async def process(argv, timeout):
        Path(argv[-1]).write_bytes(wav_bytes(state["output_frames"] / 48000))
        return b"", b""

    boundary = AsyncMock(side_effect=process)
    monkeypatch.setattr(render, "run_media_process", boundary)
    return {"raw": raw, "output": output, "reference": reference, "state": state,
            "process": boundary, "group": SimpleNamespace(
                reference=SimpleNamespace(start_sec=0, end_sec=1.6),
                source_segment_ids=["SRC_1"], translated_text="Authored fixture", speaker="A"),
            "slot": {"duration_sec": 1.3, "start_sec": 0, "end_sec": 1.3,
                     "segment_id": "DUB_0001", "flags": []}}


async def fit(voice):
    """Call the production fitter with the existing concrete group and slot."""
    return await render.fit_voice(voice["raw"], voice["output"], voice["group"], voice["slot"],
                                  {"caller_authored": True}, [{}], voice["reference"])


@pytest.mark.parametrize("seconds", [0.9, 1.3])
async def test_short_voice_bypasses_identity_tempo(voice, seconds):
    """GIVEN short or exact-fit PCM WHEN fitted THEN no buffered identity tempo runs."""
    voice["raw"].write_bytes(wav_bytes(seconds, rate=24000, channels=1))
    result = await fit(voice)
    argv = voice["process"].call_args.args[0]
    filters = argv[argv.index("-af") + 1]
    assert "atempo=" not in filters
    assert filters.startswith("afade=t=in:st=0:d=0.015,")
    assert "afade=t=out:" in filters
    assert f"adelay={round((1.3 - seconds) * 500)}:all=1" in filters
    assert filters.endswith("apad=whole_dur=1.3,atrim=duration=1.3")
    assert argv[argv.index("-ar") + 1] == "48000"
    assert argv[argv.index("-ac") + 1] == "2"
    assert result["speed"] == 1.0
    assert result["timing"] == "PASS" and result["listening"] == "UNRESOLVED"
    assert client.pcm_metadata(client.audio_bytes(voice["output"]))["duration_sec"] == 1.3
    receipt = json.loads(voice["output"].with_suffix(".wav.process.json").read_bytes())
    assert receipt["state"] == "complete" and receipt["argv"] == argv


@pytest.mark.parametrize("seconds", [1.43, 1.495, 1.534])
async def test_acceleration_and_review_flag_remain_bounded(voice, seconds):
    """GIVEN over-slot PCM within 1.18x WHEN fitted THEN retain tempo and review flags."""
    voice["raw"].write_bytes(wav_bytes(seconds, rate=24000, channels=1))
    result = await fit(voice)
    actual = client.pcm_metadata(client.audio_bytes(voice["raw"]))["duration_sec"]
    argv = voice["process"].call_args.args[0]
    filters = argv[argv.index("-af") + 1]
    assert filters.startswith(f"atempo={actual / 1.3},afade=")
    assert "adelay=0:all=1" in filters
    assert result["speed"] == actual / 1.3
    assert ("acceleration_above_1.12x" in result["flags"]) == (result["speed"] > 1.12)


@pytest.mark.parametrize("frames", [56896, 62256, 62544])
async def test_fitted_duration_still_rejects_more_than_two_ms(voice, frames):
    """GIVEN the retained failure or a 3 ms discrepancy WHEN read back THEN reject."""
    voice["state"]["output_frames"] = frames
    with pytest.raises(client.DubbingError, match="^fitted_voice_duration_invalid$"):
        await fit(voice)
    assert voice["process"].await_count == 1
    assert voice["output"].exists()
    receipt = json.loads(voice["output"].with_suffix(".wav.process.json").read_bytes())
    assert receipt["state"] == "complete"


async def test_overlong_voice_rejected_before_process(voice):
    """GIVEN speech exceeding 1.18x WHEN fitted THEN refuse before starting a process."""
    voice["raw"].write_bytes(wav_bytes(1.55, rate=24000, channels=1))
    with pytest.raises(client.DubbingError, match="^timing_failed_shorten_translation$"):
        await fit(voice)
    voice["process"].assert_not_called()
    assert not voice["output"].exists()


async def test_changed_filter_preserves_old_fitted_receipt(voice):
    """GIVEN an old identity-tempo fit WHEN repaired code resumes THEN require reconciliation."""
    filters = ("atempo=1.0,afade=t=in:st=0:d=0.015,afade=t=out:st=0.885:d=0.015,"
               "adelay=200:all=1,apad=whole_dur=1.3,atrim=duration=1.3")
    voice["state"]["output_frames"] = 56896
    await render.produce([voice["raw"]], ["-af", filters, "-ar", "48000", "-ac", "2",
                                          "-c:a", "pcm_s16le"], voice["output"])
    journal = voice["output"].with_suffix(".wav.process.json")
    old_output, old_receipt = voice["output"].read_bytes(), journal.read_bytes()
    voice["process"].reset_mock()
    with pytest.raises(client.DubbingError, match="^process_requires_reconciliation$"):
        await fit(voice)
    voice["process"].assert_not_called()
    assert voice["output"].read_bytes() == old_output and journal.read_bytes() == old_receipt
