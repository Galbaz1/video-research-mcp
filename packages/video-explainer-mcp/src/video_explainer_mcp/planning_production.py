"""Admit existing producers against the same approved project plan transaction."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from .config import get_config
from .evidence import atomic_write
from .plan_artifacts import bind_script, bind_storyboard, require_binding, storyboard_path
from .planning import plan_transaction, require_approved, save_plan
from .planning_sources import canonical, external_plan
from .prereqs import require_generation_ready
from .render_artifacts import project_revision
from .storyboard_timing import require_current_timing

STEPS = ("script", "narration", "scenes", "voiceover", "storyboard")


def generation_range(from_step: str | None, to_step: str | None, *, managed: bool) -> tuple[str, ...]:
    """Validate the exact ordered stage range before any production transaction."""
    stages = STEPS if managed else ("plan", *STEPS, "render")
    first = stages[0] if from_step is None else from_step
    last = stages[-1] if to_step is None else to_step
    if not managed:
        first = "render" if first.lower() == "render" else first
        last = "render" if last.lower() == "render" else last
    if first not in stages or last not in stages or stages.index(first) > stages.index(last):
        if managed:
            raise ValueError("Managed generation requires an ordered script-to-storyboard stage range")
        raise ValueError("Generation requires an ordered plan-to-render stage range")
    return stages[stages.index(first):stages.index(last) + 1]


@contextmanager
def production_transaction(project_id: str):
    """Leave legacy dispatch intact; serialize every managed plan producer."""
    root = get_config().resolved_projects_path.resolve()
    project = (root / project_id).resolve()
    project.relative_to(root)
    with plan_transaction(project) as (connection, state):
        if state is not None:
            require_approved(project, state)
        yield project, connection, state


def publish_external_plan(project: Path, state: dict, packet: dict) -> None:
    """Publish the derived public CLI wire from approved independent content."""
    path = (project / "plan/plan.json").resolve()
    path.relative_to(project)
    body = canonical(external_plan(state, packet))
    if len(body.encode()) > 8 * 1024 * 1024:
        raise ValueError("Compiled external plan exceeds 8 MiB")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, body)


async def produce(project: Path, connection, state: dict, args: list[str], run_cli):
    """Check approval before/after the concrete CLI call and bind actual outputs."""
    packet = require_approved(project, state)
    board_path, config_sha = storyboard_path(project)
    step = "script" if args[0] == "refine" else args[0]
    if step != "script":
        require_binding(project, state, "script")
    publish_external_plan(project, state, packet)
    result = await run_cli(*args)
    packet = require_approved(project, state)
    after_path, after_sha = storyboard_path(project)
    if after_path != board_path or after_sha != config_sha:
        raise ValueError("Project configuration changed during production")
    if step == "script":
        bind_script(project, state, packet)
    elif step == "storyboard":
        bind_storyboard(project, state, board_path)
    else:
        require_binding(project, state, "script")
        state["bindings"].pop("storyboard", None)
    save_plan(connection, state)
    return result


async def generate_steps(project: Path, connection, state: dict, project_id: str,
                         from_step: str | None, to_step: str | None, force: bool,
                         run_cli, tts_args) -> dict:
    """Run supported individual stages without the upstream plan-overwrite path."""
    steps = generation_range(from_step, to_step, managed=True)
    require_generation_ready(steps)
    outputs, elapsed = [], 0.0
    for step in steps:
        args = [step, project_id]
        if step == "storyboard" or (force and step in {"narration", "scenes"}):
            args.append("--force")
        args.extend(tts_args(step))
        result = await produce(project, connection, state, args, run_cli)
        elapsed += result.duration_seconds
        outputs.append(result.stdout.strip())
    return {"project_id": project_id, "success": True, "duration_seconds": elapsed,
            "stdout": "\n".join(outputs), "plan_revision": state["revision"],
            "factual_success": False}


def freeze_render_source(project: Path) -> dict:
    """Freeze render inputs while current approval and both bindings are admitted."""
    with plan_transaction(project) as (_, state):
        if state is not None:
            require_approved(project, state)
            require_binding(project, state, "storyboard")
            require_current_timing(project, state)
        return project_revision(project)
