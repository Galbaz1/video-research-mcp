"""Source-bound local DSP and optional pinned Rust workflows with durable job receipts."""

import json
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field, TypeAdapter

from ..audio_dsp import execute
from ..errors import ToolError
from ..image_tool_results import image_blocks
from ..models.audio_dsp import AudioDspRequest, AudioDspResponse
from ..native_media_results import native_error
from ..tracing import trace

audio_dsp_server = FastMCP("audio-dsp")
_SCHEMA = TypeAdapter(AudioDspResponse | ToolError).json_schema()
_SCHEMA["type"] = "object"


@audio_dsp_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
    ),
)
@trace(name="audio_dsp_analyze", span_type="TOOL")
async def audio_dsp_analyze(
    request: Annotated[
        AudioDspRequest,
        Field(
            description="Exact local source SHA and windows, optional reference and fixed DSP operation;30-second aggregate audio and8MiB artifact limits"
        ),
    ],
    include_image: Annotated[
        bool,
        Field(
            description="Include verified bounded waveform/spectrogram PNG blocks; text keeps exact artifact identities"
        ),
    ] = False,
) -> CallToolResult:
    """Measure audio or invoke one separately installed operator-pinned native DSP workflow.

    Local analysis preserves stereo, finite silence/abstentions and absolute
    clipping intervals. A/B uses reference-minus-primary differences with units.
    Optional Juzzy modes preserve harmonic/rhythm/masking/section observations;
    Ferrous receives an explicit mono derivation and retains heuristic quality,
    content and fingerprint output. Standards and semantic claims are unverified.
    Reusing an exact job_id reads its attested artifacts without launching again.
    Use job_status for durable status, including interrupted/failed work.

    Args:
        request: Source revisions, windows and fixed operation with immutable job identity.
        include_image: Deliver verified native PNG previews along with text metadata.

    Returns:
        Finite measurements, source/PCM identities and exact result/manifest/job
        receipts, or a terminal typed error. Native text remains attributed data.
    """
    try:
        result = await execute(request)
        if "metadata" in result:
            blocks, delivery = await image_blocks(result["metadata"], include_image)
            result = AudioDspResponse(**result, native_images=delivery).model_dump(mode="json")
            failed = result["metadata"].get("status") in {"failed", "cancelled"}
        else:
            blocks, failed = [], True
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, allow_nan=False)), *blocks],
            structured_content=result,
            is_error=failed,
        )
    except Exception as error:
        return native_error(error)
