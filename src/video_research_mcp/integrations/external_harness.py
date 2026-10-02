"""A bounded video source for external planners and report writers."""

from __future__ import annotations

import asyncio
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
from typing import Literal

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from ..models.media import Digest
from ..models.native_media import NativeMediaResult
from ..media_local_io import _open_regular


class FrameRequest(BaseModel):
    """Operator-selected source and point; the external planner cannot expand access."""

    model_config = ConfigDict(extra="forbid", strict=True)
    file_path: str = Field(min_length=1, max_length=4096)
    expected_source_sha256: Digest
    time_seconds: FiniteFloat = Field(ge=0)


class HarnessSettings(BaseModel):
    """Trusted local stdio configuration; no HTTP transport or automatic installation."""

    model_config = ConfigDict(extra="forbid", strict=True)
    transport: Literal["stdio"]
    command: str = Field(min_length=1, max_length=4096)
    args: list[str] = Field(max_length=16)
    cwd: str = Field(min_length=1, max_length=4096)
    env: dict[str, str]
    init_timeout_seconds: FiniteFloat = Field(gt=0, le=10)
    request_timeout_seconds: FiniteFloat = Field(gt=0, le=30)
    collection_timeout_seconds: FiniteFloat = Field(gt=0, le=60)
    dependencies: dict[str, str]
    capabilities: list[str]

    def client(self) -> Client:
        """Resolve explicit environment references before spawning a stdio server."""
        required = {"video_frame", "structuredContent", "text_mirror", "source_sha256",
                    "decoded_point_provenance"}
        if set(self.capabilities) != required or set(self.dependencies) != {"fastmcp", "mcp"}:
            raise ValueError("Qualify changed integration capabilities or dependency set")
        for name, expected in self.dependencies.items():
            if version(name) != expected:
                raise ValueError(f"Qualify changed integration dependency: {name}")
        transport = StdioTransport(
            command=expand(self.command), args=[expand(value) for value in self.args],
            cwd=expand(self.cwd), env={key: expand(value) for key, value in self.env.items()},
            keep_alive=False,
        )
        return Client(transport, mode="legacy", cache=False,
                      init_timeout=self.init_timeout_seconds, timeout=self.request_timeout_seconds)


def expand(value: str) -> str:
    """Expand whole-value ${ENV_NAME} references; never invoke a shell."""
    if "${" not in value:
        return value
    match = re.fullmatch(r"\$\{([A-Z_][A-Z0-9_]*)\}", value)
    if not match:
        raise ValueError("Use a whole-value environment reference")
    resolved = os.environ.get(match[1], "")
    if not resolved.strip() or "${" in resolved:
        raise ValueError(f"Missing integration environment variable: {match[1]}")
    return resolved


def load_settings(path: Path) -> HarnessSettings:
    """Read an operator-owned configuration; returned settings still contain placeholders."""
    with _open_regular(path) as stream:
        value = stream.read(16 * 1024 + 1)
    if len(value) > 16 * 1024:
        raise ValueError("Integration configuration exceeds 16 KiB")
    return HarnessSettings.model_validate_json(value)


def encoded(value: dict) -> str:
    """Use one finite JSON representation for source records and trace commitments."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def digest(value: str) -> str:
    """Commit UTF-8 representation bytes, separately from original media bytes."""
    return hashlib.sha256(value.encode()).hexdigest()


def source_record(result, request: FrameRequest) -> dict:
    """Validate the structured/text mirror and retain full point extraction provenance."""
    if result.is_error:
        raise ValueError("Video tool returned an error; no source promoted")
    value = result.structured_content
    raw = encoded(value)
    if len(raw.encode()) > 256 * 1024:
        raise ValueError("Video source result exceeds 256 KiB")
    if len(result.content) != 1 or result.content[0].type != "text":
        raise ValueError("Expected one text mirror without inline images")
    if len(result.content[0].text.encode()) > 256 * 1024:
        raise ValueError("Video text mirror exceeds 256 KiB")
    if json.loads(result.content[0].text) != value:
        raise ValueError("Video structured/text mirror differs")
    observed = NativeMediaResult.model_validate(value)
    if observed.source.sha256 != request.expected_source_sha256:
        raise ValueError("Video source differs from the selected SHA256")
    if len(observed.frames) != 1 or observed.status != "complete":
        raise ValueError("Expected one complete video point")
    frame = observed.frames[0]
    if (frame.requested_seconds != request.time_seconds or frame.actual_seconds is None
            or frame.original_pts is None or frame.time_base is None
            or frame.approximate or frame.selection_method != "first_decoded_at_or_after"):
        raise ValueError("Video point lacks matching requested/actual time")
    source_id = f"urn:sha256:{observed.source.sha256}"
    reference = f"{source_id}#t={frame.actual_seconds}"
    body = encoded({
        "tool": "video_frame", "tool_result_sha256": digest(raw),
        "source_references": [reference], "untrusted_tool_data": value,
        "factual_success": False, "watched_intervals": [],
        "limitation": "Extracted point metadata; no visual/spoken fact or continuous coverage claim",
    })
    return {"href": reference, "title": "Extracted video point", "body": body}


async def collect_frame(client: Client, request: FrameRequest, trace: list[dict],
                        timeout_seconds: float) -> dict:
    """Discover, select and call one source tool; retain failed attempts in the caller trace.

    The caller owns the client's async context and persists the trace in finally.
    No model, sampling, elicitation, shell or external agent tools are exposed.
    """
    phase = "discovery"
    try:
        async with asyncio.timeout(timeout_seconds):
            listing = await client.list_tools_mcp(cache_mode="bypass")
            trace.append({"stage": phase, "tools": [tool.name for tool in listing.tools],
                          "next_cursor": listing.next_cursor})
            if listing.next_cursor or len(listing.tools) > 100:
                raise ValueError("Expected one bounded discovery page")
            selected = [tool for tool in listing.tools if tool.name == "video_frame"]
            if len(selected) != 1 or selected[0].output_schema is None:
                raise ValueError("Required structured video_frame tool is unavailable")
            arguments = {"file_path": request.file_path, "time_seconds": request.time_seconds,
                         "selection": "precise", "max_pixels": 250_000, "include_image": False}
            trace.append({"stage": "selection", "tool": "video_frame", "arguments": arguments,
                          "tool_contract_sha256": digest(encoded(selected[0].model_dump(mode="json")))})
            phase = "call"
            trace.append({"stage": phase, "tool": "video_frame", "status": "started"})
            result = await client.session.call_tool(
                "video_frame", arguments, read_timeout_seconds=timeout_seconds,
                allow_input_required=False, allow_claimed=False,
            )
            phase = "validation"
            record = source_record(result, request)
            trace.append({"stage": "source", "tool": "video_frame", "status": "complete",
                          "tool_result_sha256": json.loads(record["body"])["tool_result_sha256"],
                          "record_sha256": digest(encoded(record)), "references": [record["href"]],
                          "factual_success": False})
            return record
    except BaseException as exc:
        trace.append({"stage": phase, "status": "failed", "error_type": type(exc).__name__,
                      "source_promoted": False})
        raise


async def query_source(settings: HarnessSettings, request: FrameRequest) -> dict:
    """Join one stdio collection before exposing the source; never retry a failed attempt."""
    trace = []
    try:
        async with asyncio.timeout(settings.collection_timeout_seconds):
            async with settings.client() as client:
                record = await collect_frame(client, request, trace, settings.request_timeout_seconds)
        trace.append({"stage": "connection", "status": "closed"})
        return {"status": "complete", "record": record, "trace": trace, "factual_success": False}
    except (Exception, asyncio.CancelledError) as exc:
        trace.append({"stage": "connection", "status": "failed", "error_type": type(exc).__name__,
                      "source_promoted": False})
        status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
        return {"status": status, "trace": trace, "factual_success": False}
