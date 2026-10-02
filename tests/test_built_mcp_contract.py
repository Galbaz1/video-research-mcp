"""Keep the installed-wheel gate sensitive to wire changes and tool omissions."""

import asyncio
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from scripts import smoke_built_mcp

from mcp.types import Tool, ToolAnnotations
import pytest

from scripts.smoke_built_mcp import check_tool_contract


def tool():
    """Return one wire contract with observable inputs, outputs and annotations."""
    return Tool(
        name="inspect_source",
        description="Inspect a source.",
        inputSchema={"type": "object", "properties": {"path": {"type": "string"}}},
        outputSchema={"type": "object"},
        annotations=ToolAnnotations(readOnlyHint=True),
    )


def test_installed_contract_matches_source():
    """Identical installed source contracts pass without a hard-coded tool count."""
    current = tool()
    check_tool_contract([current], [current.model_dump(by_alias=True, exclude_none=True)])


@pytest.mark.parametrize(
    "change", ["missing", "extra", "renamed", "input", "output", "annotations"]
)
def test_installed_contract_rejects_drift(change):
    """Missing tools and same-count schema drift must prevent release acceptance."""
    current = tool()
    expected = [current.model_dump(by_alias=True, exclude_none=True)]
    actual = [deepcopy(current)]
    if change == "missing":
        actual.clear()
    elif change == "extra":
        actual.append(tool())
    elif change == "renamed":
        actual[0].name = "other_source"
    elif change == "input":
        actual[0].input_schema["required"] = ["path"]
    elif change == "output":
        actual[0].output_schema = {"type": "string"}
    else:
        actual[0].annotations.read_only_hint = False
    with pytest.raises(RuntimeError, match="differs from candidate source"):
        check_tool_contract(actual, expected)


def test_installed_transport_cannot_import_from_inherited_source_path(tmp_path, monkeypatch):
    """A source-path override must not replace the installed artifact's imports."""
    checkout = tmp_path / "checkout"
    installed = tmp_path / "installed"
    for root in (checkout, installed):
        (root / "candidate_probe").mkdir(parents=True)
        (root / "candidate_probe/__init__.py").write_text("")
    monkeypatch.setenv("PYTHONPATH", str(checkout))
    wheel = tmp_path / "candidate.whl"
    wheel.touch()
    captured = {}

    class BoundaryReached(Exception):
        pass

    def capture(**kwargs):
        captured.update(kwargs)
        raise BoundaryReached

    with (
        patch.object(smoke_built_mcp.subprocess, "check_output", return_value="[]"),
        patch.object(smoke_built_mcp, "StdioTransport", capture),
        pytest.raises(BoundaryReached),
    ):
        asyncio.run(smoke_built_mcp.smoke(wheel))
    code = (
        "import importlib.util,sys; sys.path.append(sys.argv[1]); "
        "print(importlib.util.find_spec('candidate_probe').origin)"
    )
    # The smoke's temporary HOME/cwd are gone; use a fresh neutral working directory.
    env = {**captured["env"], "HOME": str(tmp_path), "PATH": os.environ["PATH"]}
    origin = subprocess.check_output(
        [sys.executable, "-S", "-c", code, str(installed)],
        env=env,
        cwd=tmp_path,
        text=True,
    ).strip()
    assert Path(origin) == installed / "candidate_probe/__init__.py"
