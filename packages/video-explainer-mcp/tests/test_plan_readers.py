"""Real FIFO substitution at the file-open boundary cannot block plan readers."""

import multiprocessing
import os
from pathlib import Path
from unittest.mock import patch

import pytest


def _fifo_probe(filename, kind, sender):
    """Use an owned child so a regressed blocking read cannot hang the suite."""
    from video_explainer_mcp.evidence import _read_original_text, _source_hash
    from video_explainer_mcp.planning_sources import read_object
    from video_explainer_mcp.render_artifacts import file_revision

    path = Path(filename)
    original_open = os.open
    observed = []

    def replaced(candidate, flags, *args, **kwargs):
        if Path(candidate) == path:
            path.unlink()
            os.mkfifo(path)
            observed.append(flags)
        return original_open(candidate, flags, *args, **kwargs)

    with patch("os.open", side_effect=replaced):
        try:
            if kind == "json":
                read_object(path, path.parent)
            elif kind == "text":
                _read_original_text(path)
            elif kind == "media":
                _source_hash(path)
            else:
                file_revision(path)
        except (OSError, ValueError) as error:
            sender.send({"error": str(error), "flags": observed})
        else:
            sender.send({"error": None, "flags": observed})
    sender.close()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO replacement control")
@pytest.mark.parametrize("kind", ["json", "text", "media", "render"])
def test_regular_file_replaced_at_open_is_rejected_without_blocking(tmp_path, kind):
    path = tmp_path / "original.json"
    path.write_text('{"source":"original regular bytes"}')
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_fifo_probe, args=(str(path), kind, sender))
    process.start()
    sender.close()
    try:
        process.join(5)
        assert not process.is_alive(), "File replacement blocked on a FIFO with no writer"
        assert process.exitcode == 0 and receiver.poll(1)
        result = receiver.recv()
        assert "regular" in result["error"]
        assert len(result["flags"]) == 1 and result["flags"][0] & os.O_NONBLOCK
    finally:
        if process.is_alive():
            process.terminate()
            process.join(3)
        assert not process.is_alive()
        receiver.close()
