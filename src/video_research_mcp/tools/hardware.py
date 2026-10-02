"""Six bounded simulated device operations with separate host authority."""

import asyncio
import json
from pathlib import Path
import time
from typing import Annotated, Literal

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, JsonValue

from ..config import get_config
from ..errors import make_tool_error
from ..image_preprocessing import check_worker, image_worker
from ..tracing import trace

hardware_server = FastMCP("hardware")
DeviceId = Annotated[str, Field(min_length=1, max_length=128,
                              description="Qualified simulator adapter/device ID")]
Capability = Annotated[str, Field(min_length=1, max_length=64,
                                description="Capability declared by mhs_meta_info")]
CommandId = Annotated[str, Field(min_length=1, max_length=128,
                               description="Explicit command ID; replay reads its receipt without executing again")]
Params = Annotated[dict[str, JsonValue], Field(max_length=16,
                                             description="Exact capability parameters; unknown fields are refused")]


def _operate(operation, arguments, cancelled, deadline):
    """Run the concrete simulator with a check at each commit boundary."""
    cfg = get_config()
    if cfg.mhs_mode != "simulator":
        raise PermissionError("Hardware is disabled; select MHS_MODE=simulator for local controls. "
                              "Physical adapters require named owner qualification and are unavailable.")
    from ..hardware_simulator import SimulatedHardware
    body = json.dumps(arguments, allow_nan=False, ensure_ascii=False)
    if len(body.encode()) > 8192:
        raise ValueError("Hardware arguments exceed the 8192-byte operation ceiling")
    def check():
        check_worker(cancelled, deadline)
    check()
    directory = Path(cfg.cache_dir).expanduser() / "hardware"
    device = SimulatedHardware(directory / "simulator.sqlite3", directory / "artifacts",
                               Path(cfg.mhs_authority_file) if cfg.mhs_authority_file else None,
                               check=check)
    return getattr(device, operation)(*arguments)


async def _invoke(operation, *arguments):
    """Join the owned bounded worker before returning a result or error."""
    try:
        timeout = min(get_config().media_acquire_timeout_seconds, 10)
        async with asyncio.timeout(timeout):
            return await image_worker(_operate, operation, arguments,
                                      deadline=time.monotonic() + timeout)
    except Exception as error:
        if isinstance(error, TimeoutError) and not str(error):
            error = TimeoutError("Hardware simulator deadline exceeded; owned work joined")
        return make_tool_error(error)


@hardware_server.tool(annotations=ToolAnnotations(
    readOnlyHint=True, idempotentHint=True, openWorldHint=False,
))
@trace(name="mhs_discover", span_type="TOOL")
async def mhs_discover(
    device_type: Annotated[str | None, Field(max_length=64,
                                           description="Optional exact simulated device type")] = None,
    tag: Annotated[str | None, Field(max_length=64,
                                   description="Optional exact device tag")] = None,
) -> dict:
    """Discover registered simulated devices and their explicit capabilities.

    Args:
        device_type: Optional device type filter.
        tag: Optional device tag filter.

    Returns:
        Simulated registration metadata or an actionable disabled/error result.
    """
    return await _invoke("discover", device_type, tag)


@hardware_server.tool(annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False,
))
@trace(name="mhs_health_check", span_type="TOOL")
async def mhs_health_check(
    device_id: Annotated[str | None, Field(max_length=128,
                                         description="Qualified device ID; omit for all simulated devices")] = None,
) -> dict:
    """Inspect fresh simulated health and acknowledge a failed-write health gate.

    Args:
        device_id: One qualified device or all registered devices.

    Returns:
        Current simulated state and health evidence; physical calibration is unknown.
    """
    return await _invoke("health", device_id)


@hardware_server.tool(annotations=ToolAnnotations(
    readOnlyHint=True, idempotentHint=True, openWorldHint=False,
))
@trace(name="mhs_meta_info", span_type="TOOL")
async def mhs_meta_info(device_id: DeviceId) -> dict:
    """Inspect current device values, directions and effective simulated limits.

    Args:
        device_id: Qualified simulator device ID.

    Returns:
        Exact metadata and current state without cached physical assumptions.
    """
    return await _invoke("meta", device_id)


@hardware_server.tool(annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False,
))
@trace(name="mhs_read", span_type="TOOL")
async def mhs_read(device_id: DeviceId, capability: Capability, params: Params) -> dict:
    """Read declared simulated sensors or retain independently generated image bytes.

    Args:
        device_id: Qualified simulator device ID.
        capability: Declared read capability.
        params: Exact read parameters, including an empty object when none apply.

    Returns:
        Simulated observations and owned artifact commitments, never physical evidence.
    """
    return await _invoke("read", device_id, capability, params)


@hardware_server.tool(annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False,
))
@trace(name="mhs_write", span_type="TOOL")
async def mhs_write(
    device_id: DeviceId, capability: Capability, params: Params, command_id: CommandId,
    confirm: Annotated[bool, Field(strict=True,
                                  description="Caller acknowledgement only; never grants host authority")] = False,
) -> dict:
    """Apply one atomic simulated write or return its exact authority proposal.

    Soft overrides and confirmation-required operations need separate host
    approval bound to this command, state and limits. confirm=True grants no
    approval. Terminal IDs replay their receipt. An explicitly resumed pending
    proposal may attempt its first action after exact host approval.

    Args:
        device_id: Qualified simulator device ID.
        capability: Declared write capability.
        params: Exact requested values.
        command_id: Explicit single-operation identity.
        confirm: Caller acknowledgement with no independent authority.

    Returns:
        Command, limits and before/after state, or a refusal/host-authority proposal.
    """
    return await _invoke("write", device_id, capability, params, command_id, confirm)


@hardware_server.tool(annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False,
))
@trace(name="mhs_reset", span_type="TOOL")
async def mhs_reset(
    device_id: DeviceId, mode: Annotated[Literal["soft", "estop"], Field(
        description="estop latches simulated output off; soft recovery requires host authority")],
    command_id: CommandId,
) -> dict:
    """Latch a simulated emergency stop or perform separately authorized recovery.

    Args:
        device_id: Qualified simulator device ID.
        mode: Requested stop or safe-default recovery.
        command_id: Explicit command identity, also used for receipt replay.

    Returns:
        Recorded simulated command and state; physical stop effectiveness is unknown.
    """
    return await _invoke("reset", device_id, mode, command_id)
