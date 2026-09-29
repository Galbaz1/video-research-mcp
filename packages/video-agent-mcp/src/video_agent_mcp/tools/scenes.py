"""Scene generation tools — parallel and single-scene via Agent SDK.

Reads project data (script.json, voiceover manifest), builds per-scene
prompts, runs them in parallel via ``sdk_runner``, extracts TSX code
from responses, and writes scene files to disk.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..config import get_config
from ..errors import make_tool_error
from ..prompts.scene import (
    SCENE_GENERATION_PROMPT,
    SCENE_SYSTEM_PROMPT,
    extract_code,
    format_word_timestamps,
    title_to_component_name,
    title_to_scene_key,
)
from ..prompts.scene_templates import (
    REFERENCE_TEMPLATE,
    generate_index_content,
    generate_styles_content,
)
from ..sdk_runner import run_agent_query, run_parallel_queries
from ..types import AgentResult, ProjectId, SceneResult

logger = logging.getLogger(__name__)

scenes_server = FastMCP("scenes")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_script(project_dir: Path) -> dict:
    """Load script.json from a project directory."""
    script_path = project_dir / "script" / "script.json"
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")
    return json.loads(script_path.read_text())


def _read_voiceover_manifest(project_dir: Path) -> dict[str, list[dict]]:
    """Load word timestamps from voiceover/manifest.json.

    Returns:
        Dict mapping scene_id to list of word timestamp dicts.
    """
    manifest_path = project_dir / "voiceover" / "manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text())
    result: dict[str, list[dict]] = {}
    for scene_data in manifest.get("scenes", []):
        scene_id = scene_data.get("scene_id", "")
        result[scene_id] = scene_data.get("word_timestamps", [])
    return result


def _build_scene_prompt(
    scene: dict,
    scene_number: int,
    scenes_dir: Path,
    word_timestamps: list[dict],
) -> dict:
    """Build a prompt dict for a single scene.

    Returns:
        Dict with ``prompt``, ``system_prompt``, and metadata keys.
    """
    title = scene.get("title", f"Scene {scene_number}")
    scene_type = scene.get("scene_type", "explanation")
    duration = scene.get("duration_seconds", 20)
    voiceover = scene.get("voiceover", "")

    if "visual_cue" in scene:
        visual_desc = scene["visual_cue"].get("description", "")
        elements = scene["visual_cue"].get("elements", [])
    else:
        visual_desc = scene.get("visual_description", "")
        elements = scene.get("key_elements", [])

    component_name = title_to_component_name(title)
    scene_key = title_to_scene_key(title)
    filename = f"{component_name}.tsx"
    output_path = scenes_dir / filename
    elements_str = "\n".join(f"- {e}" for e in elements) if elements else "- General scene elements"
    word_timestamps_section = format_word_timestamps(word_timestamps, voiceover, duration)

    prompt = SCENE_GENERATION_PROMPT.format(
        scene_number=scene_number,
        title=title,
        scene_type=scene_type,
        duration=duration,
        total_frames=int(duration * 30),
        voiceover=voiceover,
        visual_description=visual_desc,
        elements=elements_str,
        component_name=component_name,
        example_scene="// (No example scene provided — follow the system prompt patterns)",
        output_path=output_path,
        word_timestamps_section=word_timestamps_section,
    )

    return {
        "prompt": f"{prompt}\n\nReturn ONLY the complete React/TypeScript component code. "
        "No markdown fences, no explanation.",
        "system_prompt": SCENE_SYSTEM_PROMPT,
        "scene_number": scene_number,
        "title": title,
        "component_name": component_name,
        "filename": filename,
        "scene_key": scene_key,
        "output_path": str(output_path),
    }


def _write_infrastructure(scenes_dir: Path, project_title: str) -> None:
    """Write styles.ts and Reference.tsx (no LLM needed)."""
    scenes_dir.mkdir(parents=True, exist_ok=True)

    styles_path = scenes_dir / "styles.ts"
    styles_path.write_text(generate_styles_content(project_title))

    components_dir = scenes_dir / "components"
    components_dir.mkdir(parents=True, exist_ok=True)
    reference_path = components_dir / "Reference.tsx"
    reference_path.write_text(REFERENCE_TEMPLATE)


def _process_scene_result(
    prompt_info: dict,
    result: AgentResult,
    scenes_dir: Path,
) -> SceneResult:
    """Extract TSX from an AgentResult and write the scene file.

    Returns:
        SceneResult with success/error status.
    """
    scene_number = prompt_info["scene_number"]
    title = prompt_info["title"]
    component_name = prompt_info["component_name"]
    filename = prompt_info["filename"]
    scene_key = prompt_info["scene_key"]

    if not result.success:
        return SceneResult(
            scene_number=scene_number,
            title=title,
            component_name=component_name,
            filename=filename,
            scene_key=scene_key,
            success=False,
            error=result.error or "Unknown agent error",
        )

    code = extract_code(result.text)
    if not code:
        return SceneResult(
            scene_number=scene_number,
            title=title,
            component_name=component_name,
            filename=filename,
            scene_key=scene_key,
            success=False,
            error="Could not extract TSX code from agent response",
        )

    output_path = scenes_dir / filename
    output_path.write_text(code)

    return SceneResult(
        scene_number=scene_number,
        title=title,
        component_name=component_name,
        filename=filename,
        scene_key=scene_key,
        success=True,
    )


def _collect_generated_scenes(script: dict, scenes_dir: Path) -> list[dict]:
    """Collect generated scene descriptors from files that exist on disk."""
    generated: list[dict] = []
    for idx, scene in enumerate(script.get("scenes", []), start=1):
        title = scene.get("title", f"Scene {idx}")
        component_name = title_to_component_name(title)
        filename = f"{component_name}.tsx"
        if not (scenes_dir / filename).is_file():
            continue
        generated.append(
            {
                "scene_number": idx,
                "title": title,
                "component_name": component_name,
                "filename": filename,
                "scene_key": title_to_scene_key(title),
            }
        )
    return generated


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@scenes_server.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True),
)
async def agent_generate_scenes(
    project_id: ProjectId,
    concurrency: Annotated[
        int, Field(description="Max parallel scene queries (1-10)", ge=1, le=10)
    ] = 5,
    force: Annotated[
        bool, Field(description="Overwrite existing scenes if True")
    ] = False,
) -> dict:
    """Generate all Remotion scene components for a project in parallel.

    Reads script.json and voiceover/manifest.json from the project,
    builds per-scene prompts, runs them through Claude in parallel via
    the Agent SDK, extracts TSX code from responses, and writes scene
    files + index.ts to disk.

    Partial failure is supported: if 5/7 scenes succeed, those 5 are
    written and indexed; the 2 failures are reported in ``errors``.
    Failed scenes can be retried with ``agent_generate_single_scene``.

    Args:
        project_id: Explainer project directory name.
        concurrency: Max parallel agent queries.
        force: Overwrite existing scene files.

    Returns:
        Dict with ``scenes``, ``errors``, ``wall_clock_seconds``, ``scenes_dir``.
    """
    try:
        cfg = get_config()
        project_dir = cfg.get_project_dir(project_id)
        script = _read_script(project_dir)
        scenes_dir = project_dir / "scenes"

        # Check for existing scenes
        if scenes_dir.exists() and not force:
            existing = list(scenes_dir.glob("*.tsx"))
            if existing:
                raise FileExistsError(
                    f"Scenes already exist ({len(existing)} files). Use force=True to overwrite."
                )

        # Load voiceover timestamps
        timestamps_by_scene = _read_voiceover_manifest(project_dir)

        project_title = script.get("title", "Untitled")

        # Build per-scene prompts
        scene_prompts: list[dict] = []
        prompt_infos: list[dict] = []
        for idx, scene in enumerate(script.get("scenes", [])):
            scene_num = idx + 1
            scene_id = scene.get("scene_id", f"scene{scene_num}")
            word_timestamps = timestamps_by_scene.get(scene_id, [])

            info = _build_scene_prompt(scene, scene_num, scenes_dir, word_timestamps)
            if any(
                info["filename"] == previous["filename"]
                or info["scene_key"] == previous["scene_key"]
                for previous in prompt_infos
            ):
                raise ValueError("Scene titles must produce unique component filenames and keys")
            prompt_infos.append(info)
            scene_prompts.append({
                "prompt": info["prompt"],
                "system_prompt": info["system_prompt"],
            })

        if not scene_prompts:
            return {
                "scenes": [],
                "errors": [],
                "wall_clock_seconds": 0,
                "scenes_dir": str(scenes_dir),
            }

        _write_infrastructure(scenes_dir, project_title)

        # Run all scenes in parallel
        start = time.monotonic()
        results = await run_parallel_queries(scene_prompts, concurrency=concurrency)
        wall_clock = time.monotonic() - start

        # Process results
        succeeded: list[dict] = []
        failed: list[dict] = []

        for info, result in zip(prompt_infos, results):
            scene_result = _process_scene_result(info, result, scenes_dir)
            entry = {
                "scene_number": scene_result.scene_number,
                "title": scene_result.title,
                "component_name": scene_result.component_name,
                "filename": scene_result.filename,
                "scene_key": scene_result.scene_key,
            }
            if scene_result.success:
                succeeded.append(entry)
            else:
                entry["error"] = scene_result.error
                failed.append(entry)

        # Generate index.ts from successful scenes
        if succeeded:
            index_content = generate_index_content(succeeded, project_title)
            (scenes_dir / "index.ts").write_text(index_content)

        return {
            "scenes": succeeded,
            "errors": failed,
            "wall_clock_seconds": round(wall_clock, 1),
            "scenes_dir": str(scenes_dir),
        }

    except Exception as exc:
        return make_tool_error(exc)


@scenes_server.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True),
)
async def agent_generate_single_scene(
    project_id: ProjectId,
    scene_number: Annotated[
        int, Field(description="1-indexed scene number to generate", ge=1)
    ],
) -> dict:
    """Generate or regenerate a single Remotion scene component.

    Useful for retrying failed scenes from ``agent_generate_scenes``
    or regenerating a specific scene after script changes.

    Args:
        project_id: Explainer project directory name.
        scene_number: Which scene to generate (1-indexed).

    Returns:
        Dict with scene result or error.
    """
    try:
        cfg = get_config()
        project_dir = cfg.get_project_dir(project_id)
        script = _read_script(project_dir)
        scenes_dir = project_dir / "scenes"
        scenes_dir.mkdir(parents=True, exist_ok=True)

        scenes = script.get("scenes", [])
        if scene_number < 1 or scene_number > len(scenes):
            raise ValueError(
                f"scene_number {scene_number} out of range (1-{len(scenes)})"
            )

        scene = scenes[scene_number - 1]
        scene_id = scene.get("scene_id", f"scene{scene_number}")
        timestamps_by_scene = _read_voiceover_manifest(project_dir)
        word_timestamps = timestamps_by_scene.get(scene_id, [])

        info = _build_scene_prompt(scene, scene_number, scenes_dir, word_timestamps)

        start = time.monotonic()
        result = await run_agent_query(
            prompt=info["prompt"],
            system_prompt=info["system_prompt"],
        )
        wall_clock = time.monotonic() - start

        scene_result = _process_scene_result(info, result, scenes_dir)
        if scene_result.success:
            generated_scenes = _collect_generated_scenes(script, scenes_dir)
            if generated_scenes:
                project_title = script.get("title", "Untitled")
                index_content = generate_index_content(generated_scenes, project_title)
                (scenes_dir / "index.ts").write_text(index_content)

        response = {
            "scene_number": scene_result.scene_number,
            "title": scene_result.title,
            "component_name": scene_result.component_name,
            "filename": scene_result.filename,
            "scene_key": scene_result.scene_key,
            "success": scene_result.success,
            "wall_clock_seconds": round(wall_clock, 1),
        }
        if scene_result.error:
            response["error"] = scene_result.error

        return response

    except Exception as exc:
        return make_tool_error(exc)
