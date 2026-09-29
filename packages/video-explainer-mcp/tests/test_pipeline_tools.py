"""Tests for pipeline execution tools."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from video_explainer_mcp.jobs import JobStatus, clear_jobs, get_job
from video_explainer_mcp.tools.pipeline import (
    explainer_generate,
    explainer_render,
    explainer_render_poll,
    explainer_render_start,
    explainer_short,
    explainer_step,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_jobs_for_pipeline():
    clear_jobs()
    yield
    clear_jobs()


def _mock_cli_result(stdout: str = "OK", duration: float = 1.0):
    """Create a mock SubprocessResult."""
    mock = AsyncMock()
    mock.stdout = stdout
    mock.stderr = ""
    mock.returncode = 0
    mock.duration_seconds = duration
    return mock


class TestExplainerGenerate:
    """Tests for explainer_generate tool."""

    async def test_full_pipeline(self, monkeypatch):
        """Runs full pipeline with mock TTS."""
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        with patch("video_explainer_mcp.tools.pipeline.run_cli", return_value=_mock_cli_result()):
            result = await explainer_generate(project_id="test")
        assert result["success"] is True

    async def test_partial_pipeline(self, monkeypatch):
        """Runs from/to subset."""
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        with patch("video_explainer_mcp.tools.pipeline.run_cli", return_value=_mock_cli_result()) as mock_cli:
            result = await explainer_generate(
                project_id="test", from_step="narration", to_step="scenes"
            )
        assert result["success"] is True
        call_args = mock_cli.call_args.args
        assert "--from" in call_args
        assert "narration" in call_args

    async def test_force_flag(self, monkeypatch):
        """Passes --force when requested."""
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        with patch("video_explainer_mcp.tools.pipeline.run_cli", return_value=_mock_cli_result()) as mock_cli:
            await explainer_generate(project_id="test", force=True)
        assert "--force" in mock_cli.call_args.args

    async def test_error_handling(self, monkeypatch):
        """Returns tool error on failure."""
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        from video_explainer_mcp.errors import SubprocessError
        with patch(
            "video_explainer_mcp.tools.pipeline.run_cli",
            side_effect=SubprocessError(["cli"], 1, stderr="Step failed"),
        ):
            result = await explainer_generate(project_id="fail")
        assert "error" in result


class TestExplainerStep:
    """Tests for explainer_step tool."""

    async def test_single_step(self, monkeypatch):
        """Runs a single step."""
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        with patch("video_explainer_mcp.tools.pipeline.run_cli", return_value=_mock_cli_result()):
            result = await explainer_step(project_id="test", step="script")
        assert result["step"] == "script"
        assert result["success"] is True

    async def test_tts_provider_args(self, monkeypatch):
        """Passes --provider for voiceover step."""
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        monkeypatch.setenv("EXPLAINER_TTS_PROVIDER", "elevenlabs")
        with patch("video_explainer_mcp.tools.pipeline.run_cli", return_value=_mock_cli_result()) as mock_cli:
            await explainer_step(project_id="test", step="voiceover")
        call_args = mock_cli.call_args.args
        assert "--provider" in call_args
        assert "elevenlabs" in call_args

    async def test_tts_args_generate(self, monkeypatch):
        """Passes --voice-provider for generate subcommand."""
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        monkeypatch.setenv("EXPLAINER_TTS_PROVIDER", "elevenlabs")
        with patch("video_explainer_mcp.tools.pipeline.run_cli", return_value=_mock_cli_result()) as mock_cli:
            await explainer_generate(project_id="test")
        call_args = mock_cli.call_args.args
        assert "--voice-provider" in call_args
        assert "elevenlabs" in call_args

    async def test_tts_args_script_no_tts(self, monkeypatch):
        """Script step does not receive TTS args."""
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        monkeypatch.setenv("EXPLAINER_TTS_PROVIDER", "elevenlabs")
        with patch("video_explainer_mcp.tools.pipeline.run_cli", return_value=_mock_cli_result()) as mock_cli:
            await explainer_step(project_id="test", step="script")
        call_args = mock_cli.call_args.args
        assert "--provider" not in call_args
        assert "--voice-provider" not in call_args
        assert "--mock" not in call_args


class TestExplainerRender:
    """Tests for explainer_render tool."""

    async def test_blocking_render(self, monkeypatch, tmp_path):
        """Blocking render completes and finds output."""
        projects = tmp_path / "projects"
        project = projects / "test"
        output = project / "output"
        output.mkdir(parents=True)

        monkeypatch.setenv("EXPLAINER_PATH", str(tmp_path))
        monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(projects))

        async def render(*args, **kwargs):
            (output / "video.mp4").write_bytes(b"rendered-video")
            return _mock_cli_result()
        with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=render):
            result = await explainer_render(project_id="test", resolution="1080p")
        assert result["success"] is True
        assert result["output_file"].endswith(".mp4")

    async def test_fast_flag(self, monkeypatch):
        """Passes --fast by default."""
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        with patch("video_explainer_mcp.tools.pipeline.run_cli", return_value=_mock_cli_result()) as mock_cli:
            await explainer_render(project_id="test")
        assert "--fast" in mock_cli.call_args.args


class TestExplainerRenderStart:
    """Tests for background render start."""

    async def test_returns_job_id(self, monkeypatch):
        """Returns a job_id and running status immediately."""
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        with patch("video_explainer_mcp.tools.pipeline.run_cli", return_value=_mock_cli_result()):
            result = await explainer_render_start(project_id="test")
        assert "job_id" in result
        assert len(result["job_id"]) == 12
        assert result["status"] == "running"

    async def test_job_is_running_immediately(self, monkeypatch):
        """Job status is RUNNING right after start."""
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        with patch("video_explainer_mcp.tools.pipeline.run_cli", return_value=_mock_cli_result()):
            result = await explainer_render_start(project_id="test")
        job = get_job(result["job_id"])
        assert job is not None
        assert job.status == JobStatus.RUNNING

    async def test_successful_background_render(self, monkeypatch, tmp_path):
        """Background render transitions job to COMPLETED with output file."""
        projects = tmp_path / "projects"
        project = projects / "test"
        output = project / "output"
        output.mkdir(parents=True)

        monkeypatch.setenv("EXPLAINER_PATH", str(tmp_path))
        monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(projects))

        # Patch must stay active while the background task runs
        async def render(*args, **kwargs):
            (output / "video.mp4").write_bytes(b"rendered-video")
            return _mock_cli_result()
        with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=render):
            result = await explainer_render_start(project_id="test")
            from video_explainer_mcp.tools.pipeline import _background_tasks
            await asyncio.gather(*list(_background_tasks))
        job = get_job(result["job_id"])
        assert job is not None
        assert job.status == JobStatus.COMPLETED
        assert job.output_file.endswith(".mp4")

    async def test_failed_background_render(self, monkeypatch):
        """Background render failure transitions job to FAILED with error."""
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        from video_explainer_mcp.errors import SubprocessError

        # Patch must stay active while the background task runs
        with patch(
            "video_explainer_mcp.tools.pipeline.run_cli",
            side_effect=SubprocessError(["cli"], 1, stderr="render crash"),
        ):
            result = await explainer_render_start(project_id="test")
            await asyncio.sleep(0.1)
        job = get_job(result["job_id"])
        assert job is not None
        assert job.status == JobStatus.FAILED
        assert "exited with code 1" in job.error


class TestExplainerRenderPoll:
    """Tests for background render polling."""

    async def test_poll_missing_job(self):
        """Returns error for unknown job ID."""
        result = await explainer_render_poll(job_id="nonexistent")
        assert "error" in result

    async def test_poll_existing_job(self):
        """Returns job status."""
        from video_explainer_mcp.jobs import JobStatus, create_job, update_job
        job = create_job("test")
        update_job(job.job_id, status=JobStatus.COMPLETED, output_file="/out.mp4")
        result = await explainer_render_poll(job_id=job.job_id)
        assert result["status"] == "completed"
        assert result["output_file"] == "/out.mp4"


class TestExplainerShort:
    """Tests for shorts generation."""

    async def test_generate_short(self, monkeypatch):
        """Generates a short video."""
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        with patch("video_explainer_mcp.tools.pipeline.run_cli", return_value=_mock_cli_result()):
            result = await explainer_short(project_id="test")
        assert result["success"] is True


@pytest.mark.parametrize("artifact", ["missing", "empty", "stale"])
async def test_render_requires_fresh_nonempty_artifact(artifact, monkeypatch, tmp_path):
    """Exit zero cannot prove a render when output is missing, empty, or from an earlier job."""
    output = tmp_path / "projects" / "test" / "output"
    output.mkdir(parents=True)
    if artifact == "stale":
        (output / "old.mp4").write_bytes(b"old-render")
    monkeypatch.setenv("EXPLAINER_PATH", str(tmp_path))
    async def render(*args, **kwargs):
        if artifact == "empty":
            (output / "empty.mp4").touch()
        return _mock_cli_result()
    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=render):
        result = await explainer_render("test")
    assert "error" in result
    assert "no new nonempty video" in result["error"]


async def test_background_render_requires_artifact(monkeypatch, tmp_path):
    """The background path uses the same artifact gate as the blocking path."""
    from video_explainer_mcp.tools.pipeline import _background_tasks
    monkeypatch.setenv("EXPLAINER_PATH", str(tmp_path))
    with patch("video_explainer_mcp.tools.pipeline.run_cli", return_value=_mock_cli_result()):
        result = await explainer_render_start("test")
        await asyncio.gather(*list(_background_tasks))
    job = get_job(result["job_id"])
    assert job.status == JobStatus.FAILED
    assert "no new nonempty video" in job.error


@pytest.mark.parametrize("wait_until_started", [False, True])
async def test_shutdown_cancels_and_joins_background_render(
    wait_until_started, monkeypatch, tmp_path,
):
    """Shutdown leaves a terminal failed job and no task running in the background."""
    from video_explainer_mcp.server import _lifespan, app
    from video_explainer_mcp.tools.pipeline import _background_tasks
    started = asyncio.Event()
    async def slow_render(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setenv("EXPLAINER_PATH", str(tmp_path))
    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=slow_render):
        async with _lifespan(app):
            result = await explainer_render_start("test")
            if wait_until_started:
                await started.wait()
    assert not _background_tasks
    assert get_job(result["job_id"]).status == JobStatus.FAILED
    assert "cancelled" in get_job(result["job_id"]).error


@pytest.mark.parametrize("first_background", [False, True])
@pytest.mark.parametrize("second_background", [False, True])
async def test_overlapping_same_project_renders_are_rejected(
    first_background, second_background, monkeypatch, tmp_path,
):
    """A second resolution cannot claim the first render's video in either tool path."""
    from video_explainer_mcp.tools.pipeline import _background_tasks, _active_render_projects
    output = tmp_path / "projects" / "test" / "output"
    output.mkdir(parents=True)
    monkeypatch.setenv("EXPLAINER_PATH", str(tmp_path))
    started = asyncio.Event()
    release = asyncio.Event()
    async def render(*args, **kwargs):
        started.set()
        await release.wait()
        (output / "video.mp4").write_bytes(b"first-resolution")
        return _mock_cli_result()
    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=render) as cli:
        if first_background:
            first_reply = await explainer_render_start("test", resolution="720p")
            first_task = next(iter(_background_tasks))
        else:
            first_task = asyncio.create_task(explainer_render("test", resolution="720p"))
        await started.wait()
        try:
            if second_background:
                second = await explainer_render_start("test", resolution="1080p")
                await asyncio.sleep(0)
                failed = get_job(second["job_id"])
                assert failed.status == JobStatus.FAILED
                assert "already in progress" in failed.error
            else:
                second = await explainer_render("test", resolution="1080p")
                assert "already in progress" in second["error"]
            assert cli.call_count == 1
        finally:
            release.set()
            first_result = await first_task
        if first_background:
            assert get_job(first_reply["job_id"]).status == JobStatus.COMPLETED
        else:
            assert first_result["success"] is True
    assert not _active_render_projects


async def test_resolved_project_aliases_share_render_admission(monkeypatch, tmp_path):
    """Different IDs pointing at the same real project cannot render concurrently."""
    from video_explainer_mcp.tools.pipeline import _run_render
    project = tmp_path / "projects" / "test"
    project.mkdir(parents=True)
    (project.parent / "alias").symlink_to(project, target_is_directory=True)
    monkeypatch.setenv("EXPLAINER_PATH", str(tmp_path))
    started = asyncio.Event()
    async def render(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()
    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=render) as cli:
        first = asyncio.create_task(_run_render("test", "720p", True))
        await started.wait()
        try:
            with pytest.raises(RuntimeError, match="already in progress"):
                await _run_render("alias", "1080p", True)
            assert cli.call_count == 1
        finally:
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first


async def test_different_projects_can_render_concurrently(monkeypatch, tmp_path):
    """Project admission does not serialize independent video work."""
    from video_explainer_mcp.tools.pipeline import _run_render
    projects = tmp_path / "projects"
    for name in ["one", "two"]:
        (projects / name / "output").mkdir(parents=True)
    monkeypatch.setenv("EXPLAINER_PATH", str(tmp_path))
    both_started = asyncio.Event()
    active = 0
    async def render(*args, **kwargs):
        nonlocal active
        active += 1
        if active == 2:
            both_started.set()
        await both_started.wait()
        (projects / args[1] / "output" / "video.mp4").write_bytes(b"rendered")
        return _mock_cli_result()
    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=render):
        results = await asyncio.wait_for(asyncio.gather(
            _run_render("one", "720p", True), _run_render("two", "1080p", True),
        ), timeout=1)
    assert len(results) == 2


@pytest.mark.parametrize("background", [False, True])
async def test_cancelled_render_releases_project_admission(background, monkeypatch, tmp_path):
    """Cancellation frees the project so a later render can produce its own output."""
    from video_explainer_mcp.tools.pipeline import (
        _active_render_projects, _background_tasks, _run_render, cancel_background_renders,
    )
    output = tmp_path / "projects" / "test" / "output"
    output.mkdir(parents=True)
    monkeypatch.setenv("EXPLAINER_PATH", str(tmp_path))
    started = asyncio.Event()
    async def slow_render(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()
    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=slow_render):
        if background:
            await explainer_render_start("test")
        else:
            task = asyncio.create_task(_run_render("test", "720p", True))
        await started.wait()
        if background:
            await cancel_background_renders()
            assert not _background_tasks
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert not _active_render_projects
    async def render(*args, **kwargs):
        (output / "video.mp4").write_bytes(b"retry-render")
        return _mock_cli_result()
    with patch("video_explainer_mcp.tools.pipeline.run_cli", side_effect=render):
        result = await explainer_render("test", resolution="1080p")
    assert result["success"] is True
