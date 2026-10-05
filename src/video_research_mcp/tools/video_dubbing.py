"""Optional external dubbing tools registered on the root research server."""

from pathlib import Path
from typing import Annotated, Literal

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .. import dubbing_client as client
from .. import video_dubbing as workflow
from ..dubbing_contracts import validate_plan
from ..errors import make_tool_error
from ..models.video_dubbing import VadSettings
from ..tracing import trace

video_dubbing_server = FastMCP("video-dubbing")
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
PathParameter = Annotated[str, Field(min_length=1, max_length=4096, description="Exact local filesystem path within LOCAL_FILE_ACCESS_ROOT")]


def _error(exc: Exception) -> dict:
    """Expose fixed local boundary reasons without HTTP bodies or secret inputs."""
    reason = str(exc) if isinstance(exc, client.DubbingError) else "dubbing_boundary_failed"
    return make_tool_error(client.DubbingError(reason))


@video_dubbing_server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                                      idempotentHint=True, openWorldHint=True))
@trace(name="check_dubbing_service", span_type="TOOL")
async def check_dubbing_service() -> dict:
    """Check the operator's service; missing or unready is terminal readiness evidence.

    Returns:
        Readiness with separate, unqualified service acceptance.
    """
    return await client.health()


@video_dubbing_server.tool(annotations=WRITE)
@trace(name="prepare_video_translation_project", span_type="TOOL")
async def prepare_video_translation_project(
    source_movie: PathParameter,
    project_dir: PathParameter,
    target_language: Annotated[str, Field(min_length=1, max_length=128, description="Requested spoken target language")],
    expected_source_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$", description="Exact approved source bytes")],
    source_language: Annotated[str, Field(min_length=1, max_length=128, description="Source language or auto for agent detection")] = "auto",
    target: Annotated[Literal["analysis_only", "translation_only", "full", "resume"], Field(description="Requested workflow stopping point")] = "full",
    style_brief: Annotated[str, Field(max_length=10000, description="User-approved spoken translation and delivery style")] = "",
) -> dict:
    """Prepare full source PCM, local separated stems and source-bound VAD.

    Args:
        source_movie: Approved input video.
        project_dir: Durable exclusive output directory.
        target_language: Requested spoken translation language.
        expected_source_sha256: Approved source content digest.
        source_language: Declared source language or auto.
        target: Requested analysis, translation, full or resumed workflow.
        style_brief: User-approved spoken style retained in the project.

    Returns:
        Prepared analysis workflow, terminal readiness evidence or typed error.
    """
    try:
        return await workflow.prepare(source_movie, project_dir, source_language,
                                      target_language, expected_source_sha256, target, style_brief)
    except Exception as exc:
        return _error(exc)


@video_dubbing_server.tool(annotations=WRITE)
@trace(name="separate_dubbing_audio", span_type="TOOL")
async def separate_dubbing_audio(
    input_path: PathParameter, output_dir: PathParameter,
    model: Annotated[str, Field(min_length=1, max_length=128, description="Operator-licensed Demucs model name")] = "htdemucs",
) -> dict:
    """Upload local PCM and retain only validated locally downloaded stem bytes.

    Args:
        input_path: Full source PCM WAV.
        output_dir: Exclusive stem and durable intent directory.
        model: Operator-licensed separation model.

    Returns:
        Local vocal/background identities or terminal readiness/error evidence.
    """
    try:
        readiness = await client.health()
        if readiness["terminal"]:
            return {"status": "readiness_terminal", "readiness": readiness}
        return await client.separate(Path(input_path), Path(output_dir), model)
    except Exception as exc:
        return _error(exc)


@video_dubbing_server.tool(annotations=WRITE)
@trace(name="detect_dubbing_speech", span_type="TOOL")
async def detect_dubbing_speech(
    input_path: PathParameter, output_dir: PathParameter,
    settings: Annotated[VadSettings, Field(description="Pinned TEN-VAD thresholds, hop, minimum runs and padding")] = VadSettings(),
) -> dict:
    """Detect speech presence with the pinned TEN-VAD request contract.

    Args:
        input_path: Validated local separated vocal stem.
        output_dir: Exclusive durable VAD intent and response directory.
        settings: Validated TEN-VAD controls.

    Returns:
        Ordered intervals and measured duration or terminal readiness/error.
    """
    try:
        readiness = await client.health()
        if readiness["terminal"]:
            return {"status": "readiness_terminal", "readiness": readiness}
        return await client.vad(Path(input_path), Path(output_dir), settings)
    except Exception as exc:
        return _error(exc)


@video_dubbing_server.tool(annotations=WRITE)
@trace(name="synthesize_dubbing_speech", span_type="TOOL")
async def synthesize_dubbing_speech(
    text: Annotated[str, Field(min_length=1, max_length=10000, description="Exact approved translated utterance")],
    reference_audio: PathParameter,
    output_path: PathParameter,
) -> dict:
    """Synthesize one approved utterance using an actual local reference.

    Args:
        text: Exact translated utterance.
        reference_audio: Approved local PCM voice reference.
        output_path: Exclusive local WAV and durable intent path.

    Returns:
        Actual local audio identity or terminal readiness/error evidence.
    """
    try:
        readiness = await client.health()
        if readiness["terminal"]:
            return {"status": "readiness_terminal", "readiness": readiness}
        result = await client.tts(text, Path(reference_audio), Path(output_path))
        return {**result, "voice_quality": "UNQUALIFIED", "listening": "UNRESOLVED"}
    except Exception as exc:
        return _error(exc)


@video_dubbing_server.tool(annotations=READ)
@trace(name="get_video_translation_state", span_type="TOOL")
async def get_video_translation_state(project_dir: PathParameter) -> dict:
    """Derive a project's analysis, translation, rendering or review workflow.

    Args:
        project_dir: Durable local project.

    Returns:
        Actual content-bound state or typed evidence error.
    """
    try:
        return workflow.state(project_dir)
    except Exception as exc:
        return _error(exc)


@video_dubbing_server.tool(annotations=READ)
@trace(name="validate_video_translation_plan", span_type="TOOL")
async def validate_video_translation_plan(project_dir: PathParameter, plan_path: PathParameter) -> dict:
    """Require exact evidence joins, speaker references, dub groups and slots.

    Args:
        project_dir: Prepared project.
        plan_path: Complete agent-authored plan inside the project.

    Returns:
        Exact plan hash and timing diagnostics or typed validation error.
    """
    try:
        return validate_plan(Path(project_dir), Path(plan_path))[2]
    except Exception as exc:
        return _error(exc)


@video_dubbing_server.tool(annotations=WRITE)
@trace(name="render_video_translation", span_type="TOOL")
async def render_video_translation(
    project_dir: PathParameter,
    plan_path: PathParameter,
    background_mode: Annotated[Literal["include", "omit"], Field(description="Whole-stem review decision; choose include when uncertain")] = "include",
    regenerate_segment_ids: Annotated[list[str], Field(max_length=1000, description="Explicitly re-synthesize these known plan groups after review; unknown effects remain occupied")] = [],
) -> dict:
    """Render locally held validated evidence with bounded TTS and executable QA.

    Args:
        project_dir: Prepared durable project.
        plan_path: Validated complete translation plan.
        background_mode: Include the full background unless reviewed for omission.
        regenerate_segment_ids: Explicit approved affected groups to regenerate.

    Returns:
        Measured artifact/report identities, unresolved listening flags or error.
    """
    try:
        return await workflow.render_project(project_dir, plan_path, background_mode, regenerate_segment_ids)
    except Exception as exc:
        return _error(exc)


@video_dubbing_server.tool(annotations=READ)
@trace(name="validate_video_translation_delivery", span_type="TOOL")
async def validate_video_translation_delivery(project_dir: PathParameter) -> dict:
    """Recheck output hashes, all streams, full decode, stem mix and listening.

    Args:
        project_dir: Prepared project containing a current render.

    Returns:
        Separate technical and supplied listening evidence or typed error.
    """
    try:
        return await workflow.validate_delivery(project_dir)
    except Exception as exc:
        return _error(exc)
