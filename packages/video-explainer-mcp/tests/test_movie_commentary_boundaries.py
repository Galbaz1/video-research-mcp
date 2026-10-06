"""Commentary concurrency, bounded reads and segment identity regressions."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from pathlib import Path
import threading

from pydantic import TypeAdapter
import pytest

from tests.test_movie_commentary_support import approval, author, env as env, execute, frozen, prepare, segment
from video_explainer_mcp.commentary import delivery, store
from video_explainer_mcp.tools.commentary import (
    ShardId, commentary_freeze_shards, commentary_server, commentary_validate_plan,
)


@pytest.mark.parametrize("number", [1, 99, 100, 999, 1000, 2000])
def test_every_emitted_shard_identifier_is_accepted(number):
    assert TypeAdapter(ShardId).validate_python(f"shard_{number:02d}") == f"shard_{number:02d}"


async def test_swapped_script_blocks_are_not_verbatim_segment_parity(env):
    await prepare(env)
    author(env, 2, script="SEG_0001\nNarration line 2.\nSEG_0002\nNarration line 1.\n")
    result = await commentary_validate_plan(project_id="film")
    assert result["valid"] is False
    assert sum("does not preserve" in e for e in result["errors"]) == 2


@pytest.mark.parametrize("script,valid", [
    ("## SEG_0001\nNarration line 1.\n\n## SEG_0002\nNarration line 2.\n", True),
    ("SEG_0002\nNarration line 2.\nSEG_0001\nNarration line 1.\n", False),
    ("SEG_0001\nNarration line 1.\nSEG_0001\nNarration line 2.\n", False),
])
async def test_script_order_duplicates_and_formatted_headers(env, script, valid):
    await prepare(env)
    author(env, 2, script=script)
    assert (await commentary_validate_plan(project_id="film"))["valid"] is valid


async def test_hundredth_shard_approval_through_public_tool_boundary(env):
    await prepare(env)
    segments = [segment(i, visual_plan={"rough_interval_sec": [0, 1],
                                      "movie_locator": {"evidence_refs": [f"plan/watch_notes/n{i}.md"]}})
                for i in range(1, 101)]
    author(env, 100, segments=segments)
    result = await commentary_freeze_shards(project_id="film", segments_per_shard=1)
    tool = await commentary_server.get_tool("commentary_approve_shard")
    scope = await tool.run({"project_id": "film", "shard_id": "shard_100",
                           "approval": approval(env, result["shards"]["shard_100"]).model_dump()})
    assert scope.structured_content["status"] == "approved_scope_recorded"


def test_concurrent_write_once_never_replaces_the_winner(tmp_path, monkeypatch):
    target = tmp_path / "immutable.json"
    barrier = threading.Barrier(2)
    for name in ("replace", "link"):
        original = getattr(os, name)

        def publish(source, destination, *args, _original=original, **kwargs):
            if Path(destination) == target:
                barrier.wait(timeout=3)
            return _original(source, destination, *args, **kwargs)

        monkeypatch.setattr(os, name, publish)

    def write(value):
        try:
            return store.write_once(target, {"value": value})
        except FileExistsError:
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, [1, 2]))
    assert results.count("refused") == 1
    assert store.sha256(target.read_bytes()) in results


def test_write_once_reports_unstable_existing_record_as_conflict(tmp_path, monkeypatch):
    target = tmp_path / "immutable.json"
    original_value = {"value": 1}
    store.write_once(target, original_value)
    alias = tmp_path / "temporary-link"
    os.link(target, alias)
    original = store.open_regular

    @contextmanager
    def unlink_during_read(path):
        with original(path) as held:
            yield held
            alias.unlink()

    monkeypatch.setattr(store, "open_regular", unlink_during_read)
    with pytest.raises(FileExistsError, match="could not be verified"):
        store.write_once(target, {"value": 2})
    assert target.read_bytes() == store.canonical(original_value)


@pytest.mark.parametrize("kind", ["fifo", "symlink", "oversized"])
def test_record_read_rejects_nonregular_or_unbounded_input(tmp_path, monkeypatch, kind):
    path = tmp_path / "record.json"
    monkeypatch.setattr(store, "MAX_RECORD_BYTES", 32)
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "symlink":
        original = tmp_path / "original.json"
        original.write_text("{}")
        path.symlink_to(original)
    else:
        path.write_text('{"value":"' + "x" * 64 + '"}')
    with pytest.raises((OSError, ValueError)):
        store.read_record(path)


def test_record_growth_after_descriptor_admission_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "record.json"
    path.write_text("{}")
    monkeypatch.setattr(store, "MAX_RECORD_BYTES", 32)
    original = store.open_regular

    @contextmanager
    def grow(source):
        with original(source) as held:
            source.write_text('{"value":"' + "x" * 64 + '"}')
            yield held

    monkeypatch.setattr(store, "open_regular", grow)
    with pytest.raises(ValueError, match="bounded"):
        store.read_record(path)


def test_regular_to_fifo_replacement_at_open_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "record.json"
    path.write_text("{}")
    original = os.open

    def replace(source, flags, *args, **kwargs):
        if Path(source) == path:
            path.unlink()
            os.mkfifo(path)
        return original(source, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replace)
    with pytest.raises(ValueError, match="regular"):
        store.read_record(path)


async def _deliverable(env):
    result = await frozen(env)
    for shard_id in result["shards"]:
        await execute(env, result, shard_id)


async def test_concurrent_assembly_refuses_before_second_media_launch(env, monkeypatch):
    await _deliverable(env)
    entered, release = asyncio.Event(), asyncio.Event()
    original = delivery.run_media_process
    calls = []

    async def run(command, *args, **kwargs):
        if "concat" in command:
            calls.append(command)
            entered.set()
            await release.wait()
        return await original(command, *args, **kwargs)

    monkeypatch.setattr(delivery, "run_media_process", run)
    first = asyncio.create_task(delivery.assemble("film", 0.1))
    await asyncio.wait_for(entered.wait(), 2)
    second = asyncio.create_task(delivery.assemble("film", 0.1))
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(first, second, return_exceptions=True)
    assert len(calls) == 1
    assert isinstance(results[1], FileExistsError)
    assert results[0]["overall_pass"] is True
    assert (env["root"] / "full/commentary.mp4").is_file()


@pytest.mark.parametrize("cancelled", [False, True])
async def test_cleanup_failure_preserves_media_primary_and_cancellation(env, monkeypatch, cancelled):
    await _deliverable(env)
    primary = asyncio.CancelledError("cancelled original") if cancelled else RuntimeError("media original")
    final = env["root"] / "full/commentary.mp4"

    async def fail(*_args, **_kwargs):
        final.write_bytes(b"partial cut")
        raise primary

    original = Path.unlink

    def refuse(path, *args, **kwargs):
        if path == final:
            raise PermissionError("cleanup refused")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(delivery, "run_media_process", fail)
    monkeypatch.setattr(Path, "unlink", refuse)
    with pytest.raises(type(primary)) as caught:
        await delivery.assemble("film", 0.1)
    assert caught.value is primary
    assert any("cleanup refused" in note for note in primary.__notes__)


@pytest.mark.parametrize("kind", ["output", "claim"])
async def test_public_assembly_preserves_cleanup_liability(env, monkeypatch, kind):
    await _deliverable(env)
    final = env["root"] / "full/commentary.mp4"
    claim = env["root"] / "full/.assembly-claim"

    async def fail(*_args, **_kwargs):
        final.write_bytes(b"partial cut")
        raise RuntimeError("media original")

    method = "unlink" if kind == "output" else "rmdir"
    original = getattr(Path, method)

    def refuse(path, *args, **kwargs):
        if path == (final if kind == "output" else claim):
            raise PermissionError("cleanup refused")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(delivery, "run_media_process", fail)
    monkeypatch.setattr(Path, method, refuse)
    tool = await commentary_server.get_tool("commentary_assemble")
    result = (await tool.run({"project_id": "film"})).structured_content
    assert result["error"] == "media original" and result["category"] == "UNKNOWN"
    assert result["retryable"] is False
    assert any("cleanup refused" in note for note in result["cleanup_liability"])
