"""Bounded subprocess execution for owned media acquisition operations."""

from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from .redaction import redact_text

_OUTPUT_LIMIT = 1024 * 1024


async def _read_bounded(stream: asyncio.StreamReader) -> bytes:
    """Stop oversized tool output before accumulating unbounded memory."""
    output = bytearray()
    while chunk := await stream.read(65536):
        if len(output) + len(chunk) > _OUTPUT_LIMIT:
            raise RuntimeError("Media process output exceeds 1 MiB limit")
        output.extend(chunk)
    return bytes(output)


async def _discard(stream: asyncio.StreamReader) -> None:
    """Drain a terminated process without retaining its remaining output."""
    while await stream.read(65536):
        pass


def _signal_owned(process: asyncio.subprocess.Process, sig: signal.Signals) -> None:
    """Signal only the process group created by this invocation."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, sig)
        elif process.returncode is None:
            process.send_signal(sig)
    except ProcessLookupError:
        pass


async def _cleanup(process: asyncio.subprocess.Process) -> None:
    """Reap the owned group, including children holding pipes after leader exit."""
    tasks = [asyncio.create_task(_discard(stream)) for stream in (process.stdout, process.stderr)]
    tasks.append(asyncio.create_task(process.wait()))
    try:
        _signal_owned(process, signal.SIGTERM)
        _, pending = await asyncio.wait(tasks, timeout=5)
        if pending:
            _signal_owned(process, signal.SIGKILL)
            _, pending = await asyncio.wait(tasks, timeout=5)
        if pending:
            raise RuntimeError("Owned media process cleanup could not be verified")
        for task in tasks:
            task.result()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _reap_uninterruptibly(process: asyncio.subprocess.Process) -> None:
    """Keep bounded cleanup running even when callers cancel repeatedly."""
    cleanup = asyncio.create_task(_cleanup(process))
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            continue
    cleanup.result()


async def run_media_process(
    command: list[str], timeout: float, *, cwd: Path | None = None,
) -> tuple[bytes, bytes]:
    """Run one owned command with bounded time, output and cancellation cleanup."""
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(
        *command, cwd=cwd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, start_new_session=os.name == "posix",
    ))
    try:
        process = await asyncio.shield(spawn)
    except asyncio.CancelledError:
        while not spawn.done():
            try:
                await asyncio.shield(spawn)
            except asyncio.CancelledError:
                continue
        process = spawn.result()
        await _reap_uninterruptibly(process)
        raise
    tasks = [asyncio.create_task(_read_bounded(stream)) for stream in (process.stdout, process.stderr)]
    tasks.append(asyncio.create_task(process.wait()))
    try:
        stdout, stderr, code = await asyncio.wait_for(asyncio.gather(*tasks), timeout)
        if code:
            detail = redact_text(stderr.decode(errors="replace")[-4000:]).strip()
            raise RuntimeError(f"Media process exited with status {code}: {detail}")
        return stdout, stderr
    except BaseException:
        for task in tasks:
            task.cancel()
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await _reap_uninterruptibly(process)
        raise
