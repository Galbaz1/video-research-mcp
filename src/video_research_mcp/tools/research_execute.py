"""Explicit bounded research over supplied originals or protected URL retrieval."""

from typing import Annotated
from uuid import uuid4

from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..models.research_execution import (ResearchExecutionError, ResearchExecutionRequest,
                                         ResearchExecutionResponse)
from ..research_execution_provider import failure
from ..tracing import trace
from .research import research_server

_SCHEMA = TypeAdapter(ResearchExecutionResponse | ResearchExecutionError).json_schema()
_SCHEMA["type"] = "object"


@research_server.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True),
    output_schema=_SCHEMA,
)
@trace(name="research_execute", span_type="TOOL")
async def research_execute(
    request: Annotated[ResearchExecutionRequest, Field(description="Explicit route, frozen original evidence, source rules, joined subquestions and aggregate limits")],
) -> dict:
    """Prepare or execute source-preserving research under one global allowance.

    Dry runs make no provider or URL calls. Supplied originals are byte checked.
    URL execution requires source-access authorization; inference requires
    submission authorization. Google hosted research remains a separate route.
    Unknown price ceilings fail closed. Model tiers never establish CONFIRMED.

    Args:
        request: Topic, source route, exact packet, permitted URLs and run limits.

    Returns:
        Joined run state, retained failures and a source/claim packet, or error.
    """
    parsed = None
    try:
        parsed = ResearchExecutionRequest.model_validate(request)
        if parsed.run_id is None:
            parsed = parsed.model_copy(update={"run_id": uuid4().hex})
        from ..research_workflow import execute

        return await execute(parsed)
    except Exception as error:
        return ResearchExecutionError(**failure(error), run_id=parsed.run_id if parsed else None,
            plan={}, branches=[], execution={"provider_calls": None if parsed else 0,
                                            "accounting_status": "unknown" if parsed else "not_submitted"}).model_dump(mode="json")
