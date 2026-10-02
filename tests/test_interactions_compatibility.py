"""Offline evaluation of own MIT Interactions experiment against the installed SDK.

Frozen function excerpts retain exact bodies from commit
000434257e09dfd4eef93546442de2d6c597a53d. Decorators are excluded for isolated
invocation. Original fixtures and httpx.MockTransport never call a provider.
"""

# Copyright (c) 2026 Fausto Albers. SPDX-License-Identifier: MIT.
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from google import genai
from google.genai import types
from pydantic import ValidationError

from video_research_mcp.client import GeminiClient, _resolve_thinking_level
from video_research_mcp.config import ServerConfig
from video_research_mcp.errors import make_tool_error
from video_research_mcp.models.video import SessionResponse
from video_research_mcp.persistence import SessionDB, _content_to_dict, _dict_to_content
from video_research_mcp.retry import with_retry
from video_research_mcp.sessions import SessionStore

_FROZEN = {
    "_interaction_input": r'''def _interaction_input(contents: Any) -> Any:
    """Convert Gemini Content/Part values into Interactions API input items."""
    if isinstance(contents, str):
        return contents

    from google.genai import types

    if isinstance(contents, types.Content):
        entries = [contents]
    else:
        entries = list(contents)

    input_items = []
    for entry in entries:
        if isinstance(entry, str):
            input_items.append({"type": "text", "text": entry})
            continue
        for part in entry.parts:
            if part.text:
                input_items.append({"type": "text", "text": part.text})
            elif part.file_data:
                mime_type = part.file_data.mime_type or ""
                file_uri = part.file_data.file_uri
                is_video = (
                    mime_type.startswith("video/")
                    or "youtube.com" in file_uri
                    or "youtu.be" in file_uri
                    or not mime_type
                )
                item_type = "video" if is_video else "document"
                item = {"type": item_type, "uri": file_uri}
                if mime_type:
                    item["mime_type"] = mime_type
                if item_type == "video":
                    metadata = part.video_metadata
                    if metadata and any((metadata.fps, metadata.start_offset, metadata.end_offset)):
                        item["processing"] = {
                            key: value
                            for key, value in {
                                "type": "static",
                                "fps": metadata.fps,
                                "start_offset": metadata.start_offset,
                                "end_offset": metadata.end_offset,
                            }.items()
                            if value is not None
                        }
                    else:
                        item["processing"] = "agentic"
                input_items.append(item)
            elif part.inline_data:
                mime_type = part.inline_data.mime_type or ""
                item_type = "video" if mime_type.startswith("video/") else "document"
                input_items.append(
                    {"type": item_type, "data": part.inline_data.data, "mime_type": mime_type}
                )

    return input_items''',
    "interact": r'''async def interact(
        cls,
        contents: Any,
        *,
        model: str | None = None,
        thinking_level: str | None = None,
        response_schema: dict | None = None,
        system_instruction: str | None = None,
        tools: list[types.Tool] | None = None,
        previous_interaction_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Create one Gemini Interaction and return its raw response."""
        cfg = get_config()
        request: dict[str, Any] = {
            "model": model or cfg.default_model,
            "input": _interaction_input(contents),
            "generation_config": {
                "thinking_level": _resolve_thinking_level(
                    thinking_level or cfg.default_thinking_level
                )
            },
        }
        if response_schema:
            request["response_format"] = {
                "type": "text",
                "mime_type": "application/json",
                "schema": response_schema,
            }
        if system_instruction:
            request["system_instruction"] = system_instruction
        if tools:
            request["tools"] = tools
        if previous_interaction_id:
            request["previous_interaction_id"] = previous_interaction_id

        client = cls.get()
        return await with_retry(lambda: client.aio.interactions.create(**request, **kwargs))''',
    "_content_to_dict": r'''def _content_to_dict(content: types.Content) -> dict:
    """Serialize a genai Content object to a JSON-safe dict."""
    parts = []
    for p in content.parts:
        part_dict: dict = {}
        if p.text:
            part_dict["text"] = p.text
        if p.file_data:
            part_dict["file_data"] = {
                "file_uri": p.file_data.file_uri,
                "mime_type": getattr(p.file_data, "mime_type", None),
            }
        if getattr(p, "thought", False):
            part_dict["thought"] = True
        parts.append(part_dict)
    return {"role": content.role, "parts": parts}''',
    "_dict_to_content": r'''def _dict_to_content(d: dict) -> types.Content:
    """Deserialize a dict back into a genai Content object."""
    parts = []
    for p in d["parts"]:
        if "file_data" in p:
            fd = p["file_data"]
            parts.append(
                types.Part(
                    file_data=types.FileData(
                        file_uri=fd["file_uri"],
                        mime_type=fd.get("mime_type"),
                    ),
                )
            )
        elif "text" in p:
            parts.append(types.Part(text=p["text"]))
    return types.Content(role=d["role"], parts=parts)''',
    "video_continue_session": r'''async def video_continue_session(
    session_id: Annotated[
        str, Field(min_length=1, description="Session ID from video_create_session")
    ],
    prompt: Annotated[str, Field(min_length=1, description="Follow-up question or instruction")],
) -> dict:
    """Continue analysis within an existing video session.

    Args:
        session_id: Session ID returned by video_create_session.
        prompt: Follow-up question about the video.

    Returns:
        Dict with response text and turn_count.
    """
    session = session_store.get(session_id)
    if session is None:
        return {
            "error": f"Session {session_id} not found or expired",
            "category": "API_NOT_FOUND",
            "hint": "Create a new session with video_create_session",
        }

    from google.genai import types

    if session.interaction_id:
        contents = prompt
    else:
        contents = types.Content(
            role="user",
            parts=[
                types.Part(file_data=types.FileData(file_uri=session.url)),
                types.Part(text=prompt),
            ],
        )
    user_content = types.Content(role="user", parts=[types.Part(text=prompt)])

    try:
        response = await GeminiClient.interact(
            contents,
            model=session.model or get_config().default_model,
            thinking_level="medium",
            previous_interaction_id=session.interaction_id or None,
        )
        text = response.output_text or ""
        session.interaction_id = response.id

        model_content = types.Content(
            role="model",
            parts=[types.Part(text=text)],
        )
        turn = session_store.add_turn(session_id, user_content, model_content)
        from ..weaviate_store import store_session_turn

        await store_session_turn(
            session_id,
            session.video_title,
            turn,
            prompt,
            text,
            local_filepath=session.local_filepath,
        )
        return SessionResponse(response=text, turn_count=turn).model_dump(mode="json")
    except Exception as exc:
        return make_tool_error(exc)''',
}


@pytest.fixture
def branch_namespace():
    """Load frozen pure/request/session functions with the current fixed config."""
    config = ServerConfig(gemini_api_key="original-fixture-not-real", weaviate_enabled=False)
    namespace = {
        "__package__": "video_research_mcp.tools",
        "types": types,
        "get_config": lambda: config,
        "_resolve_thinking_level": _resolve_thinking_level,
        "with_retry": with_retry,
        "make_tool_error": make_tool_error,
        "SessionResponse": SessionResponse,
    }
    exec("from __future__ import annotations\n" + "\n\n".join(_FROZEN.values()), namespace)
    return SimpleNamespace(functions=namespace, config=config)


@pytest.fixture
async def sdk_mock():
    """Use the actual public SDK with an exclusively local mock transport."""
    bodies = []
    responses = [
        {
            "id": "original-interaction",
            "status": "completed",
            "output_text": "Original answer",
            "steps": [
                {"type": "model_output", "content": [{"type": "text", "text": "Original answer"}]}
            ],
        }
    ]

    def handler(request):
        bodies.append(json.loads(request.content))
        assert len(bodies) <= 2
        return httpx.Response(200, json=responses[min(len(bodies) - 1, len(responses) - 1)])

    client = genai.Client(
        api_key="original-fixture-not-real",
        vertexai=False,
        http_options=types.HttpOptions(
            base_url="https://original-fixture.invalid",
            retry_options=types.HttpRetryOptions(attempts=1),
            async_client_args={"transport": httpx.MockTransport(handler)},
        ),
    )
    async with client.aio:
        yield SimpleNamespace(client=client, bodies=bodies, responses=responses)
    client.close()


async def _interact(branch, sdk, contents, **kwargs):
    client = SimpleNamespace(get=lambda: sdk.client)
    return await branch.functions["interact"](client, contents, **kwargs)


async def test_branch_json_and_static_video_window_reach_actual_mocked_sdk(
    branch_namespace, sdk_mock
):
    """GIVEN frozen branch payloads WHEN locally serialized THEN schema/window identity survives."""
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    contents = types.Content(
        role="user",
        parts=[
            types.Part(
                file_data=types.FileData(file_uri="files/original", mime_type="video/mp4"),
                video_metadata=types.VideoMetadata(fps=1.0, start_offset="2s", end_offset="4s"),
            ),
            types.Part(text="Original bounded prompt"),
        ],
    )
    response = await _interact(
        branch_namespace, sdk_mock, contents, response_schema=schema, store=False
    )
    body = sdk_mock.bodies[0]
    assert response.status == "completed" and response.output_text == "Original answer"
    assert body["model"] == branch_namespace.config.default_model
    assert body["response_format"] == {
        "type": "text",
        "mime_type": "application/json",
        "schema": schema,
    }
    assert body["input"][0]["type"] == "user_input"
    assert body["input"][0]["content"][0] == {
        "type": "video",
        "uri": "files/original",
        "mime_type": "video/mp4",
        "processing": {"type": "static", "fps": 1.0, "start_offset": "2s", "end_offset": "4s"},
    }
    assert body["store"] is False


async def test_branch_native_id_chaining_is_locally_supported_and_storage_is_implicit(
    branch_namespace, sdk_mock
):
    await _interact(branch_namespace, sdk_mock, "Original first prompt")
    await _interact(
        branch_namespace,
        sdk_mock,
        "Original second prompt",
        previous_interaction_id="original-interaction",
    )
    assert sdk_mock.bodies[1]["previous_interaction_id"] == "original-interaction"
    assert "store" not in sdk_mock.bodies[0] and "store" not in sdk_mock.bodies[1]
    assert (
        sdk_mock.bodies[1]["generation_config"]["thinking_level"]
        == branch_namespace.config.default_thinking_level
    )


async def test_actual_sdk_text_accessor_preserves_only_trailing_model_output(
    branch_namespace, sdk_mock
):
    sdk_mock.responses[0]["steps"] = [
        {"type": "model_output", "content": [{"type": "text", "text": "Earlier original text"}]},
        {"type": "thought", "summary": [{"type": "text", "text": "Original hidden thought"}]},
        {"type": "model_output", "content": [{"type": "text", "text": "Final original text"}]},
    ]
    response = await _interact(branch_namespace, sdk_mock, "Original prompt", store=False)
    assert response.output_text == "Final original text"
    assert response.steps[0].content[0].text == "Earlier original text"


@pytest.mark.parametrize("kind", ["binary_video", "generate_content_tool"])
async def test_branch_unsupported_inputs_fail_before_mocked_transport(
    branch_namespace, sdk_mock, kind
):
    if kind == "binary_video":
        contents = types.Content(
            parts=[types.Part.from_bytes(data=b"\x00\xffOriginal", mime_type="video/mp4")]
        )
        kwargs = {}
    else:
        contents, kwargs = (
            "Original prompt",
            {"tools": [types.Tool(google_search=types.GoogleSearch())]},
        )
    with pytest.raises(ValidationError):
        await _interact(branch_namespace, sdk_mock, contents, **kwargs)
    assert sdk_mock.bodies == []


@pytest.mark.parametrize("mime_type", ["image/png", "audio/wav"])
def test_branch_nonvideo_media_has_wrong_document_discriminator(branch_namespace, mime_type):
    contents = types.Content(
        parts=[types.Part.from_uri(file_uri="files/original", mime_type=mime_type)]
    )
    converted = branch_namespace.functions["_interaction_input"](contents)
    assert converted == [{"type": "document", "uri": "files/original", "mime_type": mime_type}]


def test_branch_flattening_loses_roles_and_function_content(branch_namespace):
    history = [
        types.Content(role="user", parts=[types.Part(text="Original question")]),
        types.Content(
            role="model",
            parts=[
                types.Part(text="Original answer", thought_signature=b"original-signature"),
                types.Part(function_call=types.FunctionCall(name="original", args={})),
            ],
        ),
    ]
    converted = branch_namespace.functions["_interaction_input"](history)
    assert converted == [
        {"type": "text", "text": "Original question"},
        {"type": "text", "text": "Original answer"},
    ]
    assert history[1].parts[0].thought_signature == b"original-signature"


def test_branch_serialization_drops_metadata_that_current_persistence_retains(branch_namespace):
    content = types.Content(
        role="model",
        parts=[
            types.Part(text="Original answer", thought_signature=b"original-signature"),
            types.Part(function_call=types.FunctionCall(name="original", args={})),
            types.Part(inline_data=types.Blob(data=b"original-bytes", mime_type="image/png")),
        ],
    )
    old = branch_namespace.functions["_dict_to_content"](
        branch_namespace.functions["_content_to_dict"](content)
    )
    current = _dict_to_content(_content_to_dict(content))
    assert old.parts[0].thought_signature is None and len(old.parts) == 1
    assert current.model_dump(mode="json") == content.model_dump(mode="json")


@pytest.mark.parametrize(
    "status", ["failed", "cancelled", "incomplete", "requires_action", "in_progress"]
)
async def test_branch_session_incorrectly_advances_noncompleted_turn(
    branch_namespace, monkeypatch, status
):
    import video_research_mcp.weaviate_store as store_module

    store = SessionStore()
    session = store.create("files/original", "general", model=branch_namespace.config.default_model)
    session.interaction_id = ""
    branch_namespace.functions["session_store"] = store
    branch_namespace.functions["GeminiClient"] = SimpleNamespace(
        interact=AsyncMock(
            return_value=SimpleNamespace(
                status=status,
                id="original-noncompleted",
                output_text=None,
            )
        )
    )
    monkeypatch.setattr(store_module, "store_session_turn", AsyncMock())
    result = await branch_namespace.functions["video_continue_session"](
        session.session_id, "Original question"
    )
    assert result == {"response": "", "turn_count": 1}
    assert session.interaction_id == "original-noncompleted" and session.turn_count == 1


async def test_branch_expired_remote_id_has_no_local_replay_fallback(branch_namespace):
    store = SessionStore()
    session = store.create("files/original", "general", model=branch_namespace.config.default_model)
    session.interaction_id = "original-expired"
    branch_namespace.functions["session_store"] = store
    interact = AsyncMock(side_effect=ValueError("Original expired remote interaction"))
    branch_namespace.functions["GeminiClient"] = SimpleNamespace(interact=interact)
    result = await branch_namespace.functions["video_continue_session"](
        session.session_id, "Original follow-up"
    )
    assert "error" in result and session.turn_count == 0
    interact.assert_awaited_once()
    assert interact.call_args.kwargs["previous_interaction_id"] == "original-expired"


def test_additive_id_column_recovers_but_current_replace_would_reset_it(tmp_path):
    """GIVEN branch's additive column WHEN restarted THEN ID survives until an unadapted current save."""
    file = str(tmp_path / "original.db")
    store = SessionStore(db_path=file)
    session = store.create(
        "files/original", "general", cache_name="original-cache", model="original-model"
    )
    store._db._conn.execute(
        "ALTER TABLE sessions ADD COLUMN interaction_id TEXT NOT NULL DEFAULT ''"
    )
    store._db._conn.execute(
        "UPDATE sessions SET interaction_id=? WHERE session_id=?",
        ("original-interaction", session.session_id),
    )
    store._db._conn.commit()
    store._db.close()
    recovered = SessionDB(file)
    assert (
        recovered._conn.execute("SELECT interaction_id FROM sessions").fetchone()[0]
        == "original-interaction"
    )
    loaded = recovered.load_sync(session.session_id)
    assert loaded.cache_name == "original-cache" and loaded.model == "original-model"
    recovered.save_sync(loaded)
    assert recovered._conn.execute("SELECT interaction_id FROM sessions").fetchone()[0] == ""
    recovered.close()


@pytest.mark.parametrize("attempts", [0, 1])
async def test_installed_sdk_create_retry_option_counts_retries_not_total_attempts(attempts):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        assert len(bodies) <= 2
        return httpx.Response(
            503,
            json={
                "error": {"code": 503, "message": "Original unavailable", "status": "UNAVAILABLE"}
            },
        )

    client = genai.Client(
        api_key="original-fixture-not-real",
        vertexai=False,
        http_options=types.HttpOptions(
            base_url="https://original-fixture.invalid",
            retry_options=types.HttpRetryOptions(attempts=attempts),
            async_client_args={"transport": httpx.MockTransport(handler)},
        ),
    )
    async with client.aio:
        with pytest.raises(Exception):
            await client.aio.interactions.create(
                model="original-configured-model", input="Original prompt", store=False
            )
    client.close()
    assert len(bodies) == 2, (
        "Re-evaluate installed SDK retry semantics before accepting a create-attempt bound"
    )


def test_current_client_constructor_keeps_credentials_out_of_logs(caplog):
    with patch.object(GeminiClient, "_clients", {}), patch("google.genai.Client", MagicMock()):
        with caplog.at_level("INFO"):
            GeminiClient.get(api_key="original-private-sentinel")
    assert "original-private-sentinel" not in caplog.text
    assert "inel" not in caplog.text
