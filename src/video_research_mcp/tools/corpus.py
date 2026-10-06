"""Supplied-observation corpus indexing, vector repair and evidence-only retrieval."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..corpus_index import mutate
from ..corpus_retrieval import query
from ..errors import ToolError, make_tool_error
from ..models.corpus import CorpusResponse, Request
from ..tracing import trace

corpus_server = FastMCP("corpus")
_SCHEMA = TypeAdapter(CorpusResponse | ToolError).json_schema()
_SCHEMA["type"] = "object"
_ADAPTER = TypeAdapter(Request)


@corpus_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                               idempotentHint=False, openWorldHint=True),
)
@trace(name="corpus_retrieve", span_type="TOOL")
async def corpus_retrieve(
    request: Annotated[Request, Field(description="Collection and revision scoped supplied observations, vector-only repair, or context-only FTS/dense/RRF retrieval")],
) -> dict:
    """Index supplied evidence or retrieve exact source context within a declared budget.

    Args:
        request: Typed operation, local database, collection, provenance and budget.

    Returns:
        Chosen evidence chunks, linked entities and source IDs, an explicit
        no-evidence result, a mutation receipt, or a typed error. No answer is
        generated. Optional graph requests address a separately operated service.
    """
    try:
        parsed = _ADAPTER.validate_python(request)
        result = await query(parsed) if parsed.action == "query" else mutate(parsed)
        return CorpusResponse.model_validate(result).model_dump(mode="json")
    except Exception as error:
        return make_tool_error(error)
