"""Actual owned subprocess limits; no provider or network calls."""

import asyncio
import gc
import json
import os
import sys

import pytest

from video_research_mcp.media_process import run_media_process


async def test_owned_process_stdout_stderr_and_exit():
    result = await run_media_process([sys.executable, '-c',
        "import sys; print('out'); print('err',file=sys.stderr)"], 2)
    assert result == (b'out\n', b'err\n')
    with pytest.raises(RuntimeError, match='status 4: failure'):
        await run_media_process([sys.executable, '-c',
            "import sys; print('failure',file=sys.stderr); sys.exit(4)"], 2)


async def test_output_limit_stops_actual_process():
    with pytest.raises(RuntimeError, match='1 MiB'):
        await run_media_process([sys.executable, '-c',
            "import sys; sys.stdout.buffer.write(b'x'*(2*1024*1024)); sys.stdout.flush()"], 2)


@pytest.mark.skipif(os.name != 'posix', reason='POSIX owned process group')
async def test_timeout_kills_child_after_parent_exit(tmp_path):
    marker = tmp_path / 'terminated'
    script = """import os,signal,time,sys
child=os.fork()
if child:
    sys.exit(0)
def terminated(*args):
    open(sys.argv[1],'w').write('owned child terminated')
    sys.exit(0)
signal.signal(signal.SIGTERM,terminated)
print('child ready',flush=True)
time.sleep(30)
"""
    with pytest.raises(TimeoutError):
        await run_media_process([sys.executable, '-c', script, str(marker)], .25)
    assert marker.read_text() == 'owned child terminated'


async def test_cancellation_reaps_actual_owned_process(tmp_path):
    ready, marker = tmp_path / 'ready', tmp_path / 'terminated'
    script = """import signal,time,sys
from pathlib import Path
def terminated(*args):
    Path(sys.argv[2]).write_text('cancelled')
    sys.exit(0)
signal.signal(signal.SIGTERM,terminated)
Path(sys.argv[1]).write_text('ready')
time.sleep(30)
"""
    task = asyncio.create_task(run_media_process([sys.executable, '-c', script,
                                                  str(ready), str(marker)], 5))
    async with asyncio.timeout(2):
        while not ready.exists():
            await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert marker.read_text() == 'cancelled'


async def test_media_command_cannot_consume_mcp_standard_input(monkeypatch):
    actual_spawn = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        assert kwargs['stdin'] == asyncio.subprocess.DEVNULL
        return await actual_spawn(*args, **kwargs)

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    stdout, _ = await run_media_process([sys.executable, '-c',
                                         "import sys; print(repr(sys.stdin.read()))"], 2)
    assert stdout == b"''\n"


async def test_repeated_cancellation_during_actual_spawn_reaps_child(monkeypatch):
    actual_spawn = asyncio.create_subprocess_exec
    spawned, release = asyncio.Event(), asyncio.Event()
    processes = []

    async def delayed_spawn(*args, **kwargs):
        process = await actual_spawn(*args, **kwargs)
        processes.append(process)
        spawned.set()
        await release.wait()
        return process

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', delayed_spawn)
    task = asyncio.create_task(run_media_process(
        [sys.executable, '-c', 'import time; time.sleep(30)'], 2))
    try:
        await asyncio.wait_for(spawned.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert processes[0].returncode is not None
    finally:
        release.set()
        for process in processes:
            if process.returncode is None:
                process.kill()
            await process.wait()
        await asyncio.gather(task, return_exceptions=True)


async def test_repeated_cancel_retrieves_actual_collector_future(tmp_path, monkeypatch, record_property):
    """GIVEN cancellation inside wait_for's join WHEN cancelled again THEN consume its original gather."""
    from video_research_mcp import media_process
    loop, errors = asyncio.get_running_loop(), []
    handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _, context: errors.append(context))
    cancelled, release = asyncio.Event(), asyncio.Event()
    original = media_process._read_bounded
    async def delayed_cancel(stream):
        try:
            return await original(stream)
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
            raise
    monkeypatch.setattr(media_process, "_read_bounded", delayed_cancel)
    ready = tmp_path / "collector-pid"
    script = "import os,time; from pathlib import Path; Path(" + repr(str(ready)) + ").write_text(str(os.getpid())); time.sleep(30)"
    task = asyncio.create_task(run_media_process([sys.executable, "-I", "-c", script], 5))
    try:
        async with asyncio.timeout(2):
            while not ready.exists():
                await asyncio.sleep(.005)
        task.cancel()
        await asyncio.wait_for(cancelled.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        gc.collect()
        await asyncio.sleep(0)
        pid = int(ready.read_text())
        record_property("owned_pids", json.dumps([pid]))
        record_property("loop_errors", json.dumps([e["message"] for e in errors]))
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert not any(not t.done() for t in asyncio.all_tasks() if t is not asyncio.current_task())
        assert errors == []
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        gc.collect()
        loop.set_exception_handler(handler)
