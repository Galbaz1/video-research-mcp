"""Generation prerequisites must fail before transactions or external dispatch."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from video_explainer_mcp.config import ServerConfig
from video_explainer_mcp.planning_production import generate_steps
from video_explainer_mcp.runner import _resolve_cli
from video_explainer_mcp.tools.pipeline import explainer_generate, explainer_step

from .test_planning import _approved, planning_project as _planning_project

planning_project = _planning_project


@pytest.fixture
def generation_environment(monkeypatch):
    """Select deterministic credential presence and a mocked Claude PATH lookup."""
    monkeypatch.setenv("EXPLAINER_TTS_PROVIDER", "elevenlabs")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("video_explainer_mcp.prereqs.shutil.which", lambda name: None)


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("step", ["script", "narration", "scenes"])
async def test_missing_claude_step_precedes_transaction(
    planning_project, generation_environment, managed, step,
):
    project, _ = planning_project
    if managed:
        await _approved(project)
    with (
        patch("video_explainer_mcp.tools.pipeline.production_transaction") as transaction,
        patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock) as cli,
    ):
        result = await explainer_step(project.name, step)
    assert "claude" in result["error"].lower()
    transaction.assert_not_called()
    cli.assert_not_awaited()
    assert set(result) == {"error", "category", "hint", "retryable"}


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("first,last", [(None, None), ("narration", "scenes"), ("scenes", "scenes")])
async def test_missing_claude_generate_precedes_all_work(
    planning_project, generation_environment, managed, first, last,
):
    project, _ = planning_project
    if managed:
        await _approved(project)
    db = project / "planning.sqlite3"
    before = hashlib.sha256(db.read_bytes()).hexdigest() if db.exists() else None
    with (
        patch("video_explainer_mcp.tools.pipeline.production_transaction") as transaction,
        patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock) as cli,
        patch("video_explainer_mcp.tools.pipeline._run_render", new_callable=AsyncMock) as render,
    ):
        result = await explainer_generate(project.name, from_step=first, to_step=last)
    assert "claude" in result["error"].lower()
    transaction.assert_not_called()
    cli.assert_not_awaited()
    render.assert_not_awaited()
    assert not (project / "plan/plan.json").exists()
    assert before == (hashlib.sha256(db.read_bytes()).hexdigest() if db.exists() else None)


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("entry", ["step", "full", "partial"])
async def test_missing_elevenlabs_key_precedes_transaction(
    planning_project, generation_environment, monkeypatch, managed, entry,
):
    project, _ = planning_project
    monkeypatch.setattr("video_explainer_mcp.prereqs.shutil.which", lambda name: "/mock/claude")
    if managed:
        await _approved(project)
    with (
        patch("video_explainer_mcp.tools.pipeline.production_transaction") as transaction,
        patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock) as cli,
    ):
        if entry == "step":
            result = await explainer_step(project.name, "voiceover")
        elif entry == "full":
            result = await explainer_generate(project.name)
        else:
            result = await explainer_generate(project.name, from_step="voiceover", to_step="storyboard")
    assert "ELEVENLABS_API_KEY" in result["error"]
    transaction.assert_not_called()
    cli.assert_not_awaited()


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("first,last", [("render", "script"), ("voiceover", "scenes"), ("bad", "storyboard"), ("SCRIPT", "script"), ("", "script"), ("script", "")])
async def test_invalid_range_fails_before_transaction(planning_project, managed, first, last):
    project, _ = planning_project
    if managed:
        await _approved(project)
    with patch("video_explainer_mcp.tools.pipeline.production_transaction") as transaction:
        result = await explainer_generate(project.name, from_step=first, to_step=last)
    assert "error" in result
    transaction.assert_not_called()


async def test_storyboard_needs_neither_claude_nor_tts_key(
    planning_project, generation_environment,
):
    project, _ = planning_project
    result_mock = MagicMock(stdout="offline storyboard", duration_seconds=0.0)
    with patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock, return_value=result_mock) as cli:
        result = await explainer_step(project.name, "storyboard")
    assert result["success"] is True
    cli.assert_awaited_once_with("storyboard", project.name)


@pytest.mark.parametrize("provider", ["mock", "edge"])
async def test_voiceover_needs_no_claude_or_elevenlabs_key(
    planning_project, generation_environment, monkeypatch, provider,
):
    project, _ = planning_project
    monkeypatch.setenv("EXPLAINER_TTS_PROVIDER", provider)
    result_mock = MagicMock(stdout="offline voiceover", duration_seconds=0.0)
    with patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock, return_value=result_mock) as cli:
        result = await explainer_step(project.name, "voiceover")
    assert result["success"] is True
    flags = ["--mock"] if provider == "mock" else ["--provider", "edge"]
    cli.assert_awaited_once_with("voiceover", project.name, *flags)


async def test_known_key_presence_is_not_echoed(planning_project, generation_environment, monkeypatch):
    project, _ = planning_project
    secret = "synthetic-private-presence-only"
    monkeypatch.setenv("ELEVENLABS_API_KEY", secret)
    result_mock = MagicMock(stdout="mocked provider boundary", duration_seconds=0.0)
    with patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock, return_value=result_mock):
        result = await explainer_step(project.name, "voiceover")
    assert result["success"] is True
    assert secret not in str(result)


async def test_unsupported_provider_precedes_work(planning_project, monkeypatch):
    project, _ = planning_project
    config = ServerConfig(projects_path=str(project.parent)).model_copy(update={"tts_provider": "unsupported"})
    with (
        patch("video_explainer_mcp.prereqs.get_config", return_value=config),
        patch("video_explainer_mcp.tools.pipeline.get_config", return_value=config),
        patch("video_explainer_mcp.tools.pipeline.production_transaction") as transaction,
    ):
        result = await explainer_step(project.name, "voiceover")
    assert "unsupported" in result["error"].lower()
    transaction.assert_not_called()


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("entry", ["step", "full", "partial"])
async def test_missing_console_precedes_transaction(planning_project, monkeypatch, managed, entry):
    project, _ = planning_project
    if managed:
        await _approved(project)
    monkeypatch.setattr("video_explainer_mcp.prereqs._resolve_cli", _resolve_cli)
    with (
        patch("video_explainer_mcp.tools.pipeline.production_transaction") as transaction,
        patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock) as cli,
    ):
        if entry == "step":
            result = await explainer_step(project.name, "storyboard")
        elif entry == "full":
            result = await explainer_generate(project.name)
        else:
            result = await explainer_generate(project.name, from_step="script", to_step="script")
    assert "Console script not found" in result["error"]
    transaction.assert_not_called()
    cli.assert_not_awaited()


@pytest.mark.parametrize("first,last", [("script", "script"), ("narration", "narration"), ("plan", "script")])
async def test_legacy_mocked_llm_ranges_need_no_claude(planning_project, monkeypatch, first, last):
    project, _ = planning_project
    monkeypatch.setattr("video_explainer_mcp.prereqs.shutil.which", lambda name: None)
    result_mock = MagicMock(stdout="mocked legacy LLM", duration_seconds=0.0)
    with patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock, return_value=result_mock) as cli:
        result = await explainer_generate(project.name, from_step=first, to_step=last)
    assert result["success"] is True
    cli.assert_awaited_once_with("generate", project.name, "--from", first, "--to", last, "--mock")


async def test_managed_mock_tts_does_not_mock_script(planning_project, monkeypatch):
    project, _ = planning_project
    await _approved(project)
    monkeypatch.setattr("video_explainer_mcp.prereqs.shutil.which", lambda name: None)
    with patch("video_explainer_mcp.tools.pipeline.production_transaction") as transaction:
        result = await explainer_generate(project.name, from_step="script", to_step="script")
    assert "claude" in result["error"].lower()
    transaction.assert_not_called()


async def test_legacy_mock_does_not_mock_scenes(planning_project, monkeypatch):
    project, _ = planning_project
    monkeypatch.setattr("video_explainer_mcp.prereqs.shutil.which", lambda name: None)
    with patch("video_explainer_mcp.tools.pipeline.production_transaction") as transaction:
        result = await explainer_generate(project.name, from_step="script", to_step="scenes")
    assert "claude" in result["error"].lower()
    transaction.assert_not_called()


async def test_empty_plan_database_retains_legacy_mock_route(planning_project, monkeypatch):
    import sqlite3

    project, _ = planning_project
    with sqlite3.connect(project / "planning.sqlite3") as connection:
        connection.execute("CREATE TABLE plan (id INTEGER PRIMARY KEY, payload TEXT)")
    monkeypatch.setattr("video_explainer_mcp.prereqs.shutil.which", lambda name: None)
    result_mock = MagicMock(stdout="mocked legacy LLM", duration_seconds=0.0)
    with patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock, return_value=result_mock):
        result = await explainer_generate(project.name, from_step="script", to_step="script")
    assert result["success"] is True


@pytest.mark.parametrize("first,last", [("render", None), ("Render", None), ("Render", "Render")])
async def test_render_only_skips_generation_console_and_provider_checks(planning_project, monkeypatch, first, last):
    project, _ = planning_project
    monkeypatch.setattr("video_explainer_mcp.prereqs._resolve_cli", _resolve_cli)
    monkeypatch.setattr("video_explainer_mcp.prereqs.shutil.which", lambda name: None)
    result_mock = MagicMock(stdout="mocked render boundary", duration_seconds=0.0)
    with (
        patch("video_explainer_mcp.tools.pipeline.require_render_ready", new_callable=AsyncMock),
        patch("video_explainer_mcp.tools.pipeline._run_render", new_callable=AsyncMock, return_value=(result_mock, "/mock/final.mp4")) as render,
        patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock) as cli,
    ):
        result = await explainer_generate(project.name, from_step=first, to_step=last)
    assert result["success"] is True
    render.assert_awaited_once_with(project.name, "720p", True)
    cli.assert_not_awaited()


@pytest.mark.parametrize("force", [False, True])
async def test_storyboard_only_uses_supported_standalone_command(planning_project, force):
    project, _ = planning_project
    result_mock = MagicMock(stdout="offline standalone storyboard", duration_seconds=3.0)
    with patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock, return_value=result_mock) as cli:
        result = await explainer_generate(project.name, from_step="storyboard", to_step="storyboard", force=force)
    cli.assert_awaited_once_with("storyboard", project.name, *(["--force"] if force else []))
    assert result["duration_seconds"] == 3.0
    assert result["stdout"] == "offline standalone storyboard"


@pytest.mark.parametrize("to_step", [None, "Render"])
async def test_full_legacy_generation_preserves_all_stage_outputs_and_duration(planning_project, to_step):
    project, _ = planning_project
    preparation = MagicMock(stdout="preparation", duration_seconds=2.0)
    storyboard = MagicMock(stdout="storyboard", duration_seconds=3.0)
    rendered = MagicMock(stdout="render", duration_seconds=4.0)
    with (
        patch("video_explainer_mcp.tools.pipeline.require_render_ready", new_callable=AsyncMock),
        patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock, side_effect=[preparation, storyboard]) as cli,
        patch("video_explainer_mcp.tools.pipeline._run_render", new_callable=AsyncMock, return_value=(rendered, "/mock/final.mp4")) as render,
    ):
        result = await explainer_generate(project.name, to_step=to_step, force=True)
    assert cli.await_args_list == [
        call("generate", project.name, "--to", "voiceover", "--force", "--mock"),
        call("storyboard", project.name, "--force"),
    ]
    render.assert_awaited_once_with(project.name, "720p", True)
    assert result["duration_seconds"] == 9.0
    assert result["stdout"] == "preparation\nstoryboard\nrender"


async def test_direct_managed_generate_checks_tail_before_plan_publication(
    planning_project, generation_environment, monkeypatch,
):
    project, _ = planning_project
    monkeypatch.setattr("video_explainer_mcp.prereqs.shutil.which", lambda name: "/mock/claude")
    with patch("video_explainer_mcp.planning_production.produce", new_callable=AsyncMock) as produce:
        with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
            await generate_steps(project, None, {}, project.name, "script", "voiceover", False,
                                 AsyncMock(), lambda step: [])
    produce.assert_not_awaited()


async def test_script_needs_no_tts_credential(planning_project, generation_environment, monkeypatch):
    project, _ = planning_project
    monkeypatch.setattr("video_explainer_mcp.prereqs.shutil.which", lambda name: "/mock/claude")
    result_mock = MagicMock(stdout="offline script boundary", duration_seconds=0.0)
    with patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock, return_value=result_mock) as cli:
        result = await explainer_step(project.name, "script")
    assert result["success"] is True
    cli.assert_awaited_once_with("script", project.name)


@pytest.mark.parametrize("invalid", ["fifo", "oversized", "-journal", "-wal", "-shm"])
async def test_invalid_plan_database_is_refused_before_sqlite_open(planning_project, invalid):
    import os

    project, _ = planning_project
    database = project / "planning.sqlite3"
    if invalid == "fifo":
        os.mkfifo(database)
    elif invalid == "oversized":
        with database.open("wb") as stream:
            stream.truncate(8 * 1024 * 1024 + 1)
    else:
        database.touch()
        target = project / "outside-sidecar"
        target.touch()
        (project / (database.name + invalid)).symlink_to(target)
    with (
        patch("video_explainer_mcp.tools.pipeline.sqlite3.connect", side_effect=AssertionError("unexpected SQLite open")) as connect,
        patch("video_explainer_mcp.tools.pipeline.production_transaction") as transaction,
        patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock) as cli,
    ):
        result = await explainer_generate(project.name, from_step="script", to_step="script")
    assert "Plan database" in result["error"]
    connect.assert_not_called()
    transaction.assert_not_called()
    cli.assert_not_awaited()
