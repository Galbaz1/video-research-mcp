"""Explicit original-history recovery and scoped local derived-memory operations."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter
from google.genai import types

from ..errors import ToolError, make_tool_error
from ..models.session_memory import SessionMemoryRequest, SessionMemoryResponse
from ..session_compaction import history_sha256, memory_key, replay_view, source_identity
from ..session_history import history_index, history_page
from ..sessions import session_store
from ..tracing import trace

session_memory_server = FastMCP("session-memory")
_SCHEMA = TypeAdapter(SessionMemoryResponse | ToolError).json_schema()
_SCHEMA["type"] = "object"


def profile(session, request):
    """Apply one exact-source learned-memory operation after origin and scope validation."""
    if session_store.memory is None:
        raise ValueError("Derived memory requires GEMINI_SESSION_DB persistence")
    key = memory_key(session)
    if request.action == "set":
        identity = source_identity(session)
        return session_store.memory.put(
            key, request.synopsis, identity.get("sha256") or identity["id"],
            history_sha256(session), request.expected_revision, origin_session_id=session.session_id,
        )
    if request.action == "delete":
        session_store.memory.delete(key, request.expected_revision)
        return None
    return session_store.memory.get(key)


@session_memory_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                               idempotentHint=False, openWorldHint=False),
)
@trace(name="session_memory", span_type="TOOL")
async def session_memory(
    request: Annotated[SessionMemoryRequest, Field(
        description="Exact origin session, workspace/notebook and source; inspect originals or explicitly edit/delete non-authoritative learned text"
    )],
) -> dict:
    """Inspect original history or read/edit/delete one explicitly scoped derived profile.

    History remains recoverable after active-session expiry when SQLite persistence
    is configured. Large inline-media pages export exact bounded private JSON.
    Memory edits require the current revision; deletion clears only derived text.
    Caller-selected scope is isolation, not an authenticated multi-user identity.
    No provider, inference, upload or global-memory search occurs.

    Args:
        request: Origin session and exact scope/source, operation, revision or page.

    Returns:
        Original SDK data or revision-bound learned text, explicitly not verified
        media evidence, or an actionable typed error.
    """
    try:
        session = session_store.archive(request.session_id, request.scope)
        if session is None or source_identity(session)["id"] != request.source_id:
            raise ValueError("Original session, workspace/notebook or source does not match")
        history, memory, selection = None, None, None
        if request.action == "history":
            history = await history_page(session, request.offset, request.limit,
                                         persisted=session_store._db is not None)
        elif request.action in {"list", "search"}:
            history = history_index(session, request)
        elif request.action == "compact":
            if session.workspace_id and session_store.memory is not None:
                memory = session_store.memory.get(memory_key(session))
            _, selection = replay_view(session, types.Content(role="user", parts=[types.Part(text="")]),
                                       memory, persisted=session_store._db is not None)
            memory = None
        else:
            memory = profile(session, request)
        return SessionMemoryResponse(status=request.action, scope=request.scope,
                                     source_id=request.source_id, memory=memory,
                                     history=history, selection=selection).model_dump(mode="json")
    except Exception as error:
        return make_tool_error(error)
