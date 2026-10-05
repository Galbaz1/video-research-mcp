"""Run the optional first-party production preflight suite without renderer SDKs."""

from __future__ import annotations

import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import tempfile
import time

import pytest

TIMEOUT_SECONDS = 10
MAX_LOG_BYTES = 1024 * 1024


def _run_node(argv: list[str], env: dict[str, str]) -> tuple[int, str]:
    """Limit each Node process to ten seconds and one MiB of combined output."""
    output = bytearray()
    deadline = time.monotonic() + TIMEOUT_SECONDS
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env) as process:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        pytest.fail("Node source check exceeded its 10-second timeout")
                    for key, _ in selector.select(remaining):
                        chunk = os.read(key.fd, min(65536, MAX_LOG_BYTES - len(output) + 1))
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        if len(output) + len(chunk) > MAX_LOG_BYTES:
                            pytest.fail("Node source check exceeded its 1 MiB log limit")
                        output.extend(chunk)
            returncode = process.wait(timeout=max(0, deadline - time.monotonic()))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    return returncode, output.decode("utf-8", errors="replace")


def test_production_entry_node_source_checks():
    """Keep all thirty preflight cases in CI when optional Node 22+ is available."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Optional production source checks require Node >=22; node is unavailable")
    env = {key: value for key, value in os.environ.items() if key not in {"NODE_OPTIONS", "NODE_PATH"}}
    returncode, version = _run_node([node, "--version"], env)
    match = re.fullmatch(r"v(\d+)\.\d+\.\d+\s*", version)
    if returncode != 0 or match is None or int(match[1]) < 22:
        pytest.skip("Optional production source checks require an available Node >=22")
    fixture = Path(__file__).parent / "fixtures" / "production_entry_source.test.mjs"
    with tempfile.TemporaryDirectory(prefix="vrm-production-node-") as scratch:
        env.update(TMPDIR=scratch, TMP=scratch, TEMP=scratch)
        returncode, output = _run_node([node, "--test-reporter=tap", str(fixture)], env)
    print(output, end="")
    assert returncode == 0, output
    for expected in ("# tests 30", "# pass 30", "# fail 0", "# skipped 0"):
        assert expected in output.splitlines(), output
