"""Real anonymous-pipe stderr visibility and bounded-prefix controls."""

import hashlib
import json
import os
import select
import threading
import time
from types import SimpleNamespace

import pytest

from video_research_mcp.audio_dsp_stdio import drain_stderr


@pytest.fixture
def stderr_pipe(tmp_path, record_property):
    """Own one real pipe and join its drain after closing the producer, even on failure."""
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, "rb")
    writer = os.fdopen(write_fd, "wb", buffering=0)
    path = tmp_path / "native-stderr.bin"
    observation = {"observed_bytes": 0, "retained_bytes": 0, "eof": False}
    errors = []

    def drain():
        """Retain a worker exception so teardown verifies the actual drain outcome."""
        try:
            drain_stderr(SimpleNamespace(stderr=reader), path, observation)
        except Exception as error:
            errors.append(repr(error))

    thread = threading.Thread(target=drain, name="test-audio-dsp-stderr")
    thread.start()
    try:
        yield writer, path, observation, thread
    finally:
        writer.close()
        thread.join(timeout=2)
        joined = not thread.is_alive()
        if joined:
            reader.close()
        record_property(
            "pipe_cleanup",
            json.dumps(
                {
                    "read_fd": read_fd,
                    "write_fd": write_fd,
                    "reader_closed": reader.closed,
                    "writer_closed": writer.closed,
                    "thread_joined": joined,
                    "errors": errors,
                    "observation_after_eof": observation,
                },
                sort_keys=True,
            ),
        )
        assert joined and reader.closed and writer.closed and not errors
        assert observation["eof"]


def test_small_stderr_visible_while_pipe_remains_open(stderr_pipe, record_property):
    """GIVEN a small real pipe message WHEN its producer stays open THEN flush its prefix."""
    writer, path, observation, thread = stderr_pipe
    data = b"small inert diagnostic\n"
    expected = hashlib.sha256(data).hexdigest()
    assert writer.write(data) == len(data)
    deadline = time.monotonic() + 1
    while observation.get("retained_sha256") != expected and time.monotonic() < deadline:
        time.sleep(0.005)
    visible = path.stat().st_size if path.exists() else None
    record_property(
        "before_eof",
        json.dumps(
            {
                "written_bytes": len(data),
                "visible_file_bytes": visible,
                "writer_open": not writer.closed,
                "thread_alive": thread.is_alive(),
                "observation": observation,
            },
            sort_keys=True,
        ),
    )
    assert visible == len(data), "small buffered pipe message stayed unavailable before EOF"
    assert path.read_bytes() == data
    assert path.stat().st_mode & 0o777 == 0o600
    assert observation == {
        "observed_bytes": len(data),
        "retained_bytes": len(data),
        "eof": False,
        "retained_sha256": expected,
        "truncated": False,
    }
    assert not writer.closed and thread.is_alive()


def test_stderr_prefix_cap_hash_and_full_count_before_eof(stderr_pipe, record_property):
    """GIVEN more than64KiB WHEN the pipe stays open THEN drain all and hash only the prefix."""
    writer, path, observation, thread = stderr_pipe
    data = bytes(range(256)) * 625
    os.set_blocking(writer.fileno(), False)
    offset = 0
    deadline = time.monotonic() + 5
    while offset < len(data) and time.monotonic() < deadline:
        try:
            offset += os.write(writer.fileno(), data[offset : offset + 4096])
        except BlockingIOError:
            select.select([], [writer.fileno()], [], max(0, deadline - time.monotonic()))
    assert offset == len(data), "stderr pipe stopped draining before the write deadline"
    deadline = time.monotonic() + 1
    while observation["observed_bytes"] != len(data) and time.monotonic() < deadline:
        time.sleep(0.005)
    expected = hashlib.sha256(data[:65536]).hexdigest()
    assert path.read_bytes() == data[:65536]
    assert path.stat().st_mode & 0o777 == 0o600
    assert observation == {
        "observed_bytes": 160000,
        "retained_bytes": 65536,
        "eof": False,
        "retained_sha256": expected,
        "truncated": True,
    }
    assert not writer.closed and thread.is_alive()
    record_property("before_eof", json.dumps(observation, sort_keys=True))


def test_empty_stderr_eof_preserves_empty_prefix_metadata(stderr_pipe):
    """GIVEN no stderr WHEN the producer closes THEN retain the exact empty digest and join."""
    writer, path, observation, thread = stderr_pipe
    writer.close()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert path.read_bytes() == b""
    assert path.stat().st_mode & 0o777 == 0o600
    assert observation == {
        "observed_bytes": 0,
        "retained_bytes": 0,
        "eof": True,
        "retained_sha256": hashlib.sha256(b"").hexdigest(),
        "truncated": False,
    }
