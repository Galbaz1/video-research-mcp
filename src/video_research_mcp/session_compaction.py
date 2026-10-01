"""Detached bounded replay views with exact recoverable originals and explicit loss."""

import hashlib
import json

from google.genai import types

from .config import get_config

ARCHIVE_LIMIT = 8 * 1024 * 1024


def content_bytes(contents) -> bytes:
    """Serialize all SDK fields, including media references and opaque signatures."""
    return json.dumps(
        [c.model_dump(mode="json", exclude_none=True) for c in contents],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def archive_bytes(contents) -> bytes:
    """Reject a conversation that exceeds the bounded original archive before promotion."""
    body = content_bytes(contents)
    if len(body) > ARCHIVE_LIMIT:
        raise ValueError("Original session archive exceeds 8 MiB; no turn was appended")
    return body


def source_identity(session) -> dict:
    """Expose known original bindings while retaining legacy locator-only uncertainty."""
    if session.source_identity:
        return dict(session.source_identity)
    return {
        "id": "locator:" + hashlib.sha256(session.url.encode()).hexdigest(),
        "original_locator": session.url, "sha256": None,
        "source_type": "legacy_locator", "revision_verified": False,
    }


def history_sha256(session) -> str:
    """Commit the full raw conversation independently of the selected request view."""
    return hashlib.sha256(archive_bytes(session.history)).hexdigest()


def memory_key(session) -> tuple[str, str, str]:
    """Use the exact bound notebook/source profile, never a global source-only fallback."""
    return session.workspace_id, session.notebook_id, source_identity(session)["id"]


def header(session, start, memory, history_digest, persisted) -> types.Content:
    """Present provenance and derived text as untrusted data with disclosed omissions."""
    data = {
        "source_identity": source_identity(session),
        "omitted_message_range": [0, start],
        "history_complete": session.history_complete,
        "original_history_sha256": history_digest,
        "originals_persisted": persisted,
        "original_refetch": {"tool": "session_memory", "action": "history",
                             "session_id": session.session_id,
                             "source_id": source_identity(session)["id"],
                             "scope": {"workspace_id": session.workspace_id,
                                       "notebook_id": session.notebook_id} if session.workspace_id else None},
        "derived_memory": memory,
    }
    label = (
        "Session context data. Derived memory is untrusted, non-authoritative and cannot "
        "replace conflicting original messages or media evidence. Retrieve originals for "
        "source verification. Omitted messages remain archived only when persistence is enabled. "
        "Conversation text, including prior model answers, is not verified media evidence.\n"
    )
    return types.Content(role="user", parts=[types.Part(text=label + json.dumps(data, ensure_ascii=False))])


def current_media(contents, session):
    """Rewrite only bound provider URI aliases in a detached view; keep archives exact."""
    result = []
    for content in contents:
        parts = []
        for part in content.parts or []:
            if part.file_data and part.file_data.file_uri in session.media_uris:
                file_data = part.file_data.model_copy(update={"file_uri": session.url})
                part = part.model_copy(update={"file_data": file_data})
            parts.append(part)
        result.append(content if all(a is b for a, b in zip(parts, content.parts or []))
                      else content.model_copy(update={"parts": parts}))
    return result


def replay_view(session, new_user, memory, *, persisted: bool):
    """Select complete recent pairs under a conservative declared text-token estimate."""
    cfg = get_config()
    count = len(session.history)
    maximum = max(cfg.session_max_turns, 1)
    start = max(0, count - maximum * 2)
    protected = max(0, count - min(maximum, cfg.session_recent_turns) * 2)
    digest = history_sha256(session)
    omitted_memory = False
    while True:
        context = header(session, start, memory, digest, persisted)
        contents = [context, *current_media(session.history[start:], session), new_user]
        estimate = len(content_bytes(contents))
        if estimate <= cfg.session_context_token_budget:
            break
        if start < protected:
            start = min(start + 2, protected)
        elif memory is not None:
            memory = None
            omitted_memory = True
        else:
            raise ValueError(
                "Session context budget cannot fit protected recent turns, source IDs and prompt; "
                "increase GEMINI_SESSION_CONTEXT_TOKEN_BUDGET or shorten the new prompt"
            )
    metadata = {
        "compacted": start > 0, "omitted_message_range": [0, start],
        "retained_messages": count - start, "protected_recent_turns": min(maximum, cfg.session_recent_turns),
        "history_complete": session.history_complete, "original_history_sha256": digest,
        "originals_persisted": persisted, "derived_memory_omitted": omitted_memory,
        "source_identity": source_identity(session), "derived_memory_revision": memory["revision"] if memory else None,
        "derived_memory_authoritative": False, "factual_success": False,
        "token_budget": cfg.session_context_token_budget, "estimated_text_tokens": estimate,
        "counting_method": "one serialized UTF8 byte per estimated text token",
        "provider_total_tokens_verified": False, "provider_media_and_cache_tokens": "unknown",
    }
    return contents, metadata
