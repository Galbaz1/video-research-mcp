"""Source-only lifecycle checks with caller-authored dummy bytes and typed observations."""

import hashlib
import json
from pathlib import Path

from pydantic import TypeAdapter
import pytest

from video_research_mcp.models.video_memory_av import AlignRequest
from video_research_mcp.models.video_memory_lifecycle import VideoMemoryLifecycleRequest
from video_research_mcp.tools.video_memory_lifecycle import video_memory_lifecycle
from video_research_mcp.video_memory import av_store, lifecycle, lifecycle_inputs

REQUEST = TypeAdapter(VideoMemoryLifecycleRequest)


def source(tmp, name="first", duration=65.0):
    """Create caller-authored transcript observations; these are not real media evidence."""
    path = tmp / f"{name}.dummy"
    data = (name + ":dummy-source").encode()
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    starts = [s for s in (1.0, 31.0, 61.0) if s + 2 < duration]
    value = {"operation": "audio_transcribe", "status": "complete", "outcome": "captions",
             "source": {"sha256": digest, "bytes": len(data), "presentation_end_seconds": duration},
             "request_sha256": "a" * 64, "selection": {"start_seconds": 0.0, "end_seconds": duration},
             "captions": [], "segments": [{"id": f"seg-{i}", "start_seconds": start,
                                            "end_seconds": start + 2, "speaker_id": "SPEAKER_00",
                                            "text": f"Caller observation {name} {i}."}
                                           for i, start in enumerate(starts)],
             "untimed_text": [], "windows": [], "attempts": [], "exports": [], "artifacts": [],
             "provenance": {"basis": "caller_authored_fixture"}, "warnings": [], "execution": {}}
    artifact = tmp / f"{name}.json"
    payload = json.dumps(value).encode()
    artifact.write_bytes(payload)
    return {"segment_id": name, "file_path": str(path), "expected_source_sha256": digest,
            "expected_source_bytes": len(data), "duration_seconds": duration,
            "artifacts": [{"kind": "transcript", "path": str(artifact),
                           "sha256": hashlib.sha256(payload).hexdigest()}]}


def request(tmp, anchor, action, **fields):
    """Validate the same discriminated contract used by the public tool."""
    return REQUEST.validate_python({"action": action, "memory_dir": str(tmp / "memory"),
                                    "expected_source_sha256": anchor["expected_source_sha256"], **fields})


def state(tmp, anchor):
    """Read actual immutable snapshots using the canonical AV loader."""
    return av_store.load(tmp / "memory", anchor["expected_source_sha256"])


def first_record(src):
    return f"utterance:{src['expected_source_sha256'][:12]}:0000:001"


def fact(src, value):
    return {"subject_id": "P001", "key": "role", "value": value, "confidence": "high",
            "evidence_ids": [first_record(src)]}


async def test_interrupted_atomic_revision_and_resume_preserve_prior_results(tmp_path, monkeypatch):
    """GIVEN interruption at publication, WHEN resuming, THEN prior accepted bytes stay exact."""
    src = source(tmp_path)
    real_link = av_store.os.link

    class Interrupted(BaseException):
        pass

    def interrupted_link(temporary, target):
        if Path(target).name == "rev-000003.json":
            raise Interrupted("injected publication interruption")
        return real_link(temporary, target)

    with monkeypatch.context() as patch:
        patch.setattr(av_store.os, "link", interrupted_link)
        with pytest.raises(Interrupted):
            await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src]))
    before = state(tmp_path, src)
    original = (tmp_path / "memory" / "rev-000002.json").read_bytes()
    checkpoint = before.history[-1]["lifecycle"]
    assert checkpoint["extracted"] == ["first:0"]
    assert sum(s["planned_windows"] for s in checkpoint["segments"]) == 3
    for snapshot in (tmp_path / "memory").glob("rev-*.json"):
        assert json.loads(snapshot.read_bytes())["revision"] >= 1
    assert not list((tmp_path / "memory").glob("*.pending"))
    result = await video_memory_lifecycle(request(tmp_path, src, "resume", expected_revision=before.revision))
    assert result["complete"] is True and result["extracted"] == result["planned"] == 3
    assert result["extracted_clips"] == ["first:0", "first:1", "first:2"]
    after = state(tmp_path, src)
    assert after.records[0].model_dump() == before.records[0].model_dump()
    assert len({r.record_id for r in after.records}) == len(after.records) == 3
    assert (tmp_path / "memory" / "rev-000002.json").read_bytes() == original
    for receipt in after.artifacts:
        data = (tmp_path / "memory" / receipt.retained).read_bytes()
        assert hashlib.sha256(data).hexdigest() == receipt.sha256


async def test_window_limit_freezes_denominator_and_status_readback(tmp_path):
    """GIVEN three planned windows, WHEN bounded to one, THEN status reports one of three."""
    src = source(tmp_path)
    result = await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src],
                                                    limits={"max_windows": 1}))
    assert result["complete"] is False
    assert (result["extracted"], result["planned"], result["stopped"]) == (1, 3, "window_limit")
    status = await video_memory_lifecycle(request(tmp_path, src, "status"))
    assert status["status"] == "incomplete" and status["extracted"] == 1
    assert len(list((tmp_path / "memory").glob("rev-*.json"))) == 2
    result = await video_memory_lifecycle(request(tmp_path, src, "resume", expected_revision=result["revision"]))
    assert result["status"] == "complete" and result["planned"] == 3


async def test_multisource_append_preserves_identity_facts_and_global_clock(tmp_path):
    """GIVEN an explicit identity link, WHEN appending, THEN IDs and cumulative facts persist."""
    first, second = source(tmp_path, duration=35), source(tmp_path, "second", 35)
    first["facts"] = [fact(first, "engineer")]
    result = await video_memory_lifecycle(request(tmp_path, first, "build", segments=[first]))
    saved = state(tmp_path, first)
    saved.revision += 1
    av_store.align(saved, AlignRequest(action="align", memory_dir=str(tmp_path / "memory"),
                                       expected_source_sha256=first["expected_source_sha256"],
                                       expected_revision=result["revision"], person_id="P001", name="Pat",
                                       basis="user_asserted", evidence_ids=[first_record(first)]), saved.revision)
    av_store.commit(tmp_path / "memory", saved, {})
    second["identity_bindings"] = {"SPEAKER_00": "P001"}
    second["facts"] = [fact(second, "manager")]
    before_records = [r.model_dump() for r in saved.records]
    result = await video_memory_lifecycle(request(tmp_path, first, "append", expected_revision=saved.revision,
                                                    segments=[second]))
    after = state(tmp_path, first)
    assert result["complete"] is True and result["planned"] == 4
    assert result["duration_seconds"] == 70 and result["clock_basis"] == "caller_asserted"
    assert [r.start_seconds for r in after.records] == [1, 31, 36, 66]
    assert [r.model_dump() for r in after.records[:2]] == before_records
    assert {r.person_id for r in after.records} == {"P001"}
    assert after.persons[0].name == "Pat" and len(after.identity_revisions) == 1
    assert {(f.value, f.status, f.basis) for f in after.facts} == {
        ("engineer", "superseded", "asserted"), ("manager", "active", "asserted")}
    assert {r.record_id.split(":")[1] for r in after.records} == {
        first["expected_source_sha256"][:12], second["expected_source_sha256"][:12]}
    assert after.source.duration_seconds == 35  # The canonical anchor remains its original source.
    timeline = await lifecycle.timeline(request(tmp_path, first, "status"))
    assert len(timeline["steps"][0]["records"]) == 4


async def test_same_speaker_label_in_new_file_does_not_assert_same_person(tmp_path):
    first, second = source(tmp_path, duration=35), source(tmp_path, "second", 35)
    result = await video_memory_lifecycle(request(tmp_path, first, "build", segments=[first]))
    await video_memory_lifecycle(request(tmp_path, first, "append", expected_revision=result["revision"],
                                        segments=[second]))
    saved = state(tmp_path, first)
    assert [p.person_id for p in saved.persons] == ["P001", "P002"]
    assert all(p.name is None and p.identity_status == "unknown" for p in saved.persons)


async def test_failed_segment_stops_all_later_work_and_retains_original_plan(tmp_path, monkeypatch):
    """GIVEN a missing second artifact, WHEN building, THEN the third segment is never processed."""
    sources = [source(tmp_path, name, 35) for name in ("first", "second", "third")]
    Path(sources[1]["artifacts"][0]["path"]).unlink()
    seen, verify = [], lifecycle_inputs.verify_source

    def record_verify(item):
        seen.append(item.segment_id)
        verify(item)

    monkeypatch.setattr(lifecycle_inputs, "verify_source", record_verify)
    result = await video_memory_lifecycle(request(tmp_path, sources[0], "build", segments=sources))
    assert result["complete"] is False and result["planned"] == 6 and result["extracted"] == 2
    assert result["stopped"] == "failed_segment" and result["failure"]["clip_id"] == "second:0"
    assert "third" not in seen
    saved = state(tmp_path, sources[0])
    assert all(r.record_id.split(":")[1] == sources[0]["expected_source_sha256"][:12] for r in saved.records)
    result = await video_memory_lifecycle(request(tmp_path, sources[0], "append", expected_revision=saved.revision,
                                                    segments=[source(tmp_path, "fourth", 35)]))
    assert "error" in result and state(tmp_path, sources[0]).revision == saved.revision


@pytest.mark.parametrize("change", ["source", "config", "artifact"])
async def test_stale_source_config_or_unprocessed_artifact_is_never_silently_reused(tmp_path, change):
    """GIVEN changed input commitments, WHEN resuming, THEN no stale result is admitted."""
    src = source(tmp_path)
    built = await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src], limits={"max_windows": 1}))
    fields = {}
    if change == "source":
        Path(src["file_path"]).write_bytes(b"changed-source")
    elif change == "config":
        fields["config"] = {"profile": "different-semantic-profile"}
    else:
        Path(src["artifacts"][0]["path"]).write_bytes(b"{}")
    result = await video_memory_lifecycle(request(tmp_path, src, "resume", expected_revision=built["revision"], **fields))
    saved = state(tmp_path, src)
    assert len(saved.records) == 1 and saved.history[-1]["lifecycle"]["extracted"] == ["first:0"]
    if change == "artifact":
        assert result["failure"]["kind"] == "reject" and result["complete"] is False
    else:
        assert result["stale"] is True and "error" in result


async def test_revision_cas_duplicate_source_and_config_unavailable_write_nothing(tmp_path):
    src = source(tmp_path)
    no_observations = {**src, "artifacts": []}
    rejected = await video_memory_lifecycle(request(tmp_path, src, "build", segments=[no_observations]))
    assert rejected["failure"] == "config" and not (tmp_path / "memory").exists()
    result = await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src]))
    revision = result["revision"]
    rejected = await video_memory_lifecycle(request(tmp_path, src, "resume", expected_revision=1))
    assert rejected["current_revision"] == revision
    rejected = await video_memory_lifecycle(request(tmp_path, src, "append", expected_revision=revision, segments=[src]))
    assert "error" in rejected and state(tmp_path, src).revision == revision


async def test_local_root_boundary_denies_source_and_memory_escape(tmp_path, monkeypatch):
    from video_research_mcp.config import get_config

    src = source(tmp_path)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setattr(get_config(), "local_file_access_root", str(allowed))
    result = await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src]))
    assert "error" in result and not (tmp_path / "memory").exists()


async def test_source_symlink_swap_is_refused_by_existing_regular_file_reader(tmp_path):
    src = source(tmp_path)
    result = await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src], limits={"max_windows": 1}))
    artifact = tmp_path / "memory" / "rev-000002.json"
    original = artifact.read_bytes()
    other = tmp_path / "external-revision.json"
    other.write_bytes(original)
    artifact.unlink()
    artifact.symlink_to(other)
    result = await video_memory_lifecycle(request(tmp_path, src, "resume", expected_revision=result["revision"]))
    assert "error" in result


async def test_cooperative_deadline_retains_frozen_incomplete_checkpoint(tmp_path, monkeypatch):
    src = source(tmp_path)
    times = iter([0.0, 0.0, 100.0, 100.0])
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: next(times, 100.0))
    result = await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src],
                                                    limits={"timeout_seconds": 1}))
    assert result["complete"] is False and result["stopped"] == "timeout"
    assert (result["extracted"], result["planned"]) == (0, 3)


async def test_source_change_during_window_prevents_publication(tmp_path, monkeypatch):
    """GIVEN a source changing after extraction, THEN the source CAS rejects the whole window."""
    from video_research_mcp.video_memory import lifecycle_records

    src = source(tmp_path)
    original = lifecycle_records.accumulate

    def changing_source(*args):
        original(*args)
        Path(src["file_path"]).write_bytes(b"source changed during processing")

    monkeypatch.setattr(lifecycle_records, "accumulate", changing_source)
    result = await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src]))
    saved = state(tmp_path, src)
    assert result["complete"] is False and result["extracted"] == 0
    assert result["failure"]["report"]["stale"] is True and saved.records == []


async def test_explicit_resume_after_missing_artifact_correction_keeps_failure_and_prior_bytes(tmp_path):
    """GIVEN one failed segment, WHEN restoring its exact original input, THEN resume keeps the failure."""
    first, second = source(tmp_path, duration=35), source(tmp_path, "second", 35)
    artifact = Path(second["artifacts"][0]["path"])
    original = artifact.read_bytes()
    artifact.unlink()
    failed = await video_memory_lifecycle(request(tmp_path, first, "build", segments=[first, second]))
    failed_snapshot = tmp_path / "memory" / f"rev-{failed['revision']:06d}.json"
    failed_bytes = failed_snapshot.read_bytes()
    failure = failed["failure"]
    artifact.write_bytes(original)
    resumed = await video_memory_lifecycle(request(tmp_path, first, "resume", expected_revision=failed["revision"]))
    saved = state(tmp_path, first)
    assert resumed["complete"] is True and resumed["planned"] == 4
    assert failure in [h.get("failure") for h in saved.history]
    assert failed_snapshot.read_bytes() == failed_bytes
    assert sum("lifecycle" in h for h in saved.history) == 1


async def test_atomic_revision_conflict_has_no_retry_or_later_publication(tmp_path, monkeypatch):
    src = source(tmp_path)
    original = av_store.publish
    attempts = []

    def competing_revision(path, data):
        attempts.append(path.name)
        if path.name == "rev-000002.json":
            return False
        return original(path, data)

    monkeypatch.setattr(av_store, "publish", competing_revision)
    result = await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src]))
    assert "error" in result and attempts.count("rev-000002.json") == 1
    assert "rev-000003.json" not in attempts and state(tmp_path, src).records == []


@pytest.mark.parametrize("redirect", ["directory", "artifact"])
async def test_canonical_artifact_symlink_escape_is_denied_before_publication(tmp_path, redirect):
    """GIVEN redirected storage children, WHEN building, THEN no out-of-memory-root write occurs."""
    src = source(tmp_path)
    root = tmp_path / "memory"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    if redirect == "directory":
        (root / "artifacts").symlink_to(outside, target_is_directory=True)
    else:
        (root / "artifacts").mkdir()
        target = outside / "private.json"
        target.write_bytes(b"private original")
        (root / "artifacts" / f"{src['artifacts'][0]['sha256']}.json").symlink_to(target)
    result = await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src]))
    assert "error" in result and not (root / "rev-000002.json").exists()
    assert sorted(p.name for p in outside.iterdir()) == ([] if redirect == "directory" else ["private.json"])
    if redirect == "artifact":
        assert target.read_bytes() == b"private original"
