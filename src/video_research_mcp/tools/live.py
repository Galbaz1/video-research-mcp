"""Local immutable live-evidence replay and an optional isolated operator capture handoff."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import ToolError, make_tool_error
from ..live_companion import prepare_capture, probe
from ..live_finalize import finalize, stop
from ..live_monitor import monitor
from ..live_replay import read, replay
from ..models.live import (
    CaptureRequest, FinalizeRequest, LiveResult, MonitorRequest, ProbeRequest,
    ReadRequest, ReplayRequest, SessionPin,
)
from ..tracing import trace

live_server = FastMCP("live-evidence")
_SCHEMA = TypeAdapter(LiveResult | ToolError).json_schema()
_SCHEMA["type"] = "object"


@live_server.tool(output_schema=_SCHEMA, annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
@trace(name="live_replay", span_type="TOOL")
async def live_replay(
    request: Annotated[ReplayRequest, Field(description="Exact local originals, four typed event kinds, declared common clock/tolerance and producer telemetry")],
) -> dict:
    """Retain and freeze a bounded replay without capture, parsing or inference.

    Args:
        request: Explicit source identities, clock mappings and immutable session revision.

    Returns:
        A pinned archive receipt or a structured error.
    """
    try:
        return replay(ReplayRequest.model_validate(request))
    except Exception as error:
        return make_tool_error(error)


@live_server.tool(output_schema=_SCHEMA, annotations=ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
@trace(name="live_read", span_type="TOOL")
async def live_read(
    request: Annotated[ReadRequest, Field(description="Pinned replay bytes and a snapshot/page-size-bound cursor")],
) -> dict:
    """Read an immutable bounded page with explicit remaining, queue and dropped state.

    Args:
        request: Archive pin, optional cursor and bounded page size.

    Returns:
        Original event timestamps and mapped rational clocks or a structured error.
    """
    try:
        return read(ReadRequest.model_validate(request))
    except Exception as error:
        return make_tool_error(error)


@live_server.tool(output_schema=_SCHEMA, annotations=ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=False))
@trace(name="live_monitor", span_type="TOOL")
async def live_monitor(
    request: Annotated[MonitorRequest, Field(description="Literal kind/text/count condition with finite checks and monotonic deadline; no corrective execution")],
) -> dict:
    """Evaluate a bounded replay condition and retain an explicit unmet result.

    Args:
        request: Pinned pages, condition and finite resource limits.

    Returns:
        Condition outcome, check count, cursor and attributed matching evidence.
    """
    try:
        return monitor(MonitorRequest.model_validate(request))
    except Exception as error:
        return make_tool_error(error)


@live_server.tool(output_schema=_SCHEMA, annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
@trace(name="live_stop", span_type="TOOL")
async def live_stop(
    pin: Annotated[SessionPin, Field(description="Exact immutable replay session/revision to seal")],
) -> dict:
    """Persist a stop record without changing or processing prior events.

    Args:
        pin: Archive identity and exact byte commitment.

    Returns:
        Durable stop metadata or a structured error.
    """
    try:
        return stop(SessionPin.model_validate(pin))
    except Exception as error:
        return make_tool_error(error)


@live_server.tool(output_schema=_SCHEMA, annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
@trace(name="live_finalize", span_type="TOOL")
async def live_finalize(
    request: Annotated[FinalizeRequest, Field(description="Pinned evidence and ordinary corpus SQLite collection/revision; unresolved intent never resubmits")],
) -> dict:
    """Stop and index original-clock evidence in the existing library without reprocessing.

    Args:
        request: Archive pin and explicit ordinary corpus destination.

    Returns:
        Finalization receipt, unresolved intent state or a structured error.
    """
    try:
        return finalize(FinalizeRequest.model_validate(request))
    except Exception as error:
        return make_tool_error(error)


@live_server.tool(output_schema=_SCHEMA, annotations=ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
@trace(name="live_capability_probe", span_type="TOOL")
async def live_capability_probe(
    request: Annotated[ProbeRequest, Field(description="Optional pinned companion checkout and explicit device nodes; filesystem/executable inspection only")],
) -> dict:
    """Observe availability and unknown recording permissions without starting recording.

    Args:
        request: Explicit local paths to inspect.

    Returns:
        Observed metadata, unsupported states and separate permission unknowns.
    """
    try:
        return probe(ProbeRequest.model_validate(request))
    except Exception as error:
        return make_tool_error(error)


@live_server.tool(output_schema=_SCHEMA, annotations=ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
@trace(name="live_capture_prepare", span_type="TOOL")
async def live_capture_prepare(
    request: Annotated[CaptureRequest, Field(description="Explicit screen/window recording operation/target/duration/retention scope for a separate operator process")],
) -> dict:
    """Prepare an isolated source-defined capture handoff or report unsupported before work.

    Args:
        request: Pinned companion, output location and caller-declared recording scope.

    Returns:
        Operator entry point or an unsupported result; recording is never started here.
    """
    try:
        return prepare_capture(CaptureRequest.model_validate(request))
    except Exception as error:
        return make_tool_error(error)
