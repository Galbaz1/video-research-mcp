"""Optional explicit text generation and read-only provider capability inspection."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import make_tool_error
from ..models.text_provider import Capability, TextFailure, TextRequest, TextResponse
from ..provider_capabilities import inspect_capabilities
from ..text_provider import generate_text
from ..tracing import trace

text_provider_server = FastMCP("text-provider")
_SCHEMA = TypeAdapter(TextResponse | TextFailure).json_schema()
_SCHEMA["type"] = "object"


@text_provider_server.tool(output_schema=_SCHEMA, annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
@trace(name="text_generate", span_type="TOOL")
async def text_generate(
    request: Annotated[TextRequest, Field(description="Configured text profile, inline JSON schema, bounded output, dry plan and explicit submission authority")],
) -> dict:
    """Generate structured text using one selected compatible HTTP endpoint.

    No default Gemini/vision account is borrowed. Sources are untrusted text;
    this operation cannot accept files, media, tools or grounded search.
    Missing input-token/currency meters cause requested hard ceilings to fail.

    Args:
        request: One configured text workflow and its explicit output contract.

    Returns:
        Planned/complete structured inference with usage or an accounted error.
    """
    return await generate_text(request)


@text_provider_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
@trace(name="provider_capabilities", span_type="TOOL")
async def provider_capabilities(
    backend: Annotated[str | None, Field(max_length=80, description="gemini, weaviate, text:profile, vision:profile, or omitted for the matrix")] = None,
    required: Annotated[list[Capability], Field(max_length=9, description="Requested capabilities to check against one exact selected route")] = [],
) -> dict:
    """Inspect configured operation support and reject unsupported selections.

    Profiles declare support; inspection performs no connectivity or model test.

    Args:
        backend: Exact configured operation family and optional profile name.
        required: Capabilities that the selected family must support.

    Returns:
        Configuration and declared operation matrix or a clear policy error.
    """
    try:
        return inspect_capabilities(backend, required)
    except Exception as error:
        return {**make_tool_error(error), "provider_calls": 0}
