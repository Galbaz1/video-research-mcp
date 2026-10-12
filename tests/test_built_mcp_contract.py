"""Keep the installed-wheel gate sensitive to wire changes and tool omissions."""

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
        patch.object(smoke_built_mcp.subprocess, "run"),
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


def test_smoke_uses_scratch_environment_and_preserves_offline_cache(tmp_path, monkeypatch):
    """A successful smoke installs and starts owned scratch bytes, then removes them."""
    wheel = tmp_path / "candidate.whl"
    wheel.touch()
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "shared-cache"))
    current = tool()
    expected = [current.model_dump(by_alias=True, exclude_none=True)]
    client = SimpleNamespace(
        list_tools=AsyncMock(return_value=[current]),
        call_tool=AsyncMock(
            return_value=SimpleNamespace(
                data={
                    "current_config": {
                        "default_model": "gemini-3.8-flash",
                        "deep_research_agent": "deep-research-preview-04-2026",
                    }
                }
            )
        ),
    )
    with (
        patch.object(
            smoke_built_mcp.subprocess, "check_output", side_effect=["unused", json.dumps(expected)]
        ),
        patch.object(smoke_built_mcp.subprocess, "run") as native,
        patch.object(smoke_built_mcp, "StdioTransport") as transport,
        patch.object(smoke_built_mcp, "Client") as clients,
        patch.object(smoke_built_mcp, "media_journey", new_callable=AsyncMock) as media,
    ):
        clients.return_value.__aenter__.return_value = client
        asyncio.run(smoke_built_mcp.smoke(wheel))
    creation, installation = native.call_args_list
    scratch = Path(creation.kwargs["cwd"])
    environment = scratch / "venv"
    assert creation.args[0] == ["uv", "venv", "--python", sys.executable, str(environment)]
    assert installation.args[0] == [
        "uv",
        "pip",
        "install",
        "--python",
        str(environment / "bin/python"),
        str(wheel),
    ]
    for call in native.call_args_list:
        assert call.kwargs["check"] is True
        assert call.kwargs["cwd"] == str(scratch)
        assert call.kwargs["env"]["UV_OFFLINE"] == "1"
        assert call.kwargs["env"]["UV_CACHE_DIR"] == str(tmp_path / "shared-cache")
    assert transport.call_args.kwargs["command"] == str(environment / "bin/video-research-mcp")
    assert transport.call_args.kwargs["args"] == []
    client.call_tool.assert_awaited_once_with("infra_configure", {})
    media.assert_awaited_once_with(client, scratch)
    assert not scratch.exists()


@pytest.mark.parametrize("failure", ["venv", "install"])
def test_native_install_failure_removes_scratch_and_never_starts_server(tmp_path, failure):
    """Failed native preparation preserves its failure and removes the scratch environment."""
    wheel = tmp_path / "candidate.whl"
    wheel.touch()
    scratch = None

    def prepare(command, *, cwd, **kwargs):
        nonlocal scratch
        scratch = Path(cwd)
        environment = scratch / "venv"
        environment.mkdir(exist_ok=True)
        (environment / "partial").touch()
        if command[1] == ("venv" if failure == "venv" else "pip"):
            raise subprocess.CalledProcessError(1, command)

    with (
        patch.object(smoke_built_mcp.subprocess, "check_output", return_value="[]"),
        patch.object(smoke_built_mcp.subprocess, "run", side_effect=prepare) as native,
        patch.object(smoke_built_mcp, "StdioTransport") as transport,
        pytest.raises(subprocess.CalledProcessError),
    ):
        asyncio.run(smoke_built_mcp.smoke(wheel))
    assert native.call_count == (1 if failure == "venv" else 2)
    transport.assert_not_called()
    assert scratch is not None and not scratch.exists()
    assert wheel.exists()
