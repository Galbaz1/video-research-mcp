"""Preserve hosted observations, identities and incomplete task results explicitly."""

import json
from datetime import datetime, timezone

from pydantic import TypeAdapter

from .models.twelvelabs import Identifier, ProviderClip, TwelveLabsResponse
from .search_provider_results import ProviderFailure, digest, parse_json, protect

_ID = TypeAdapter(Identifier)
_PRIMARY = {
    "asset_create": "asset_id", "asset_get": "asset_id",
    "index_create": "index_id",
    "indexed_asset_create": "indexed_asset_id", "indexed_asset_get": "indexed_asset_id",
    "embedding_task_create": "task_id", "embedding_task_get": "task_id",
    "entity_collection_create": "collection_id", "entity_create": "entity_id",
    "analysis_task_create": "task_id", "analysis_task_get": "task_id", "analysis_task_cancel": "task_id",
}
_PROCESSING = {"processing", "queued", "pending", "validating", "indexing"}


def identities(body, request):
    """Bind only source-confirmed identifiers without converting old video IDs."""
    ids = dict(request.ids)
    primary = _PRIMARY.get(request.operation)
    if primary:
        key = "task_id" if request.operation.startswith("analysis_task") else "_id"
        observed = _ID.validate_python(body.get(key))
        if primary in ids and observed != ids[primary]:
            raise ProviderFailure("provider_identity_conflict")
        ids[primary] = observed
    for name in ("asset_id", "index_id", "indexed_asset_id", "entity_id", "entity_collection_id"):
        if name not in body:
            continue
        target = "collection_id" if name == "entity_collection_id" else name
        observed = _ID.validate_python(body[name])
        expected = ids.get(target, request.parameters.get(name))
        if expected is not None and observed != expected:
            raise ProviderFailure("provider_identity_conflict")
        ids[target] = observed
    return ids


def remote_status(body, operation):
    """A successful HTTP exchange does not imply remote readiness or complete output."""
    status = body.get("status")
    if status in _PROCESSING:
        return "processing"
    if status in {"failed", "canceled"}:
        return status
    if operation in {"analysis_task_create", "analysis_task_get", "analysis_task_cancel"}:
        if status != "ready":
            return "unknown"
        result = body.get("result")
        if not isinstance(result, dict) or result.get("data") is None:
            return "unknown"
        if result.get("finish_reason") != "stop" or body.get("error"):
            return "partial"
        return "ready"
    if operation == "analysis_sync":
        if body.get("data") is None:
            return "unknown"
        return "complete" if body.get("finish_reason") == "stop" and not body.get("error") else "partial"
    if operation in {"embedding_task_create", "embedding_task_get"}:
        if status == "ready" and isinstance(body.get("data"), list) and body["data"] and not body.get("error"):
            return "ready"
        return "unknown"
    if operation in {"asset_create", "asset_get", "indexed_asset_get", "entity_create"}:
        return "ready" if status == "ready" and not body.get("error") else "unknown"
    if operation == "indexed_asset_create":
        return "processing"
    return "complete" if status is None else "unknown"


def clip_results(body, request):
    """Keep exact seconds and every malformed result in the fixed provider population."""
    rows = body.get("data")
    if not isinstance(rows, list) or len(rows) > 50:
        raise ProviderFailure("search_population_invalid_or_over_limit")
    index_id = request.parameters["index_id"]
    pool = body.get("search_pool")
    if isinstance(pool, dict) and pool.get("index_id", index_id) != index_id:
        raise ProviderFailure("search_index_identity_conflict")
    if request.parameters.get("group_by", "clip") == "video":
        return [], []  # Grouped DTOs stay in provider_data; no guessed clip schema.
    clips, rejected = [], []
    for index, row in enumerate(rows):
        try:
            clip = ProviderClip(index_id=index_id, video_id=row["video_id"], start=row["start"],
                end=row["end"], rank=row.get("rank"), provider_reference=(
                    f"urn:twelvelabs:index:{index_id}:video:{row['video_id']}#t={row['start']},{row['end']}"))
            clips.append(clip)
        except (ValueError, TypeError, KeyError):
            rejected.append({"index": index, "code": "malformed_provider_clip"})
    return clips, rejected


def text_bytes(value):
    """Count every returned JSON string without silently truncating provider content."""
    if isinstance(value, str):
        return len(value.encode())
    if isinstance(value, list):
        return sum(text_bytes(v) for v in value)
    if isinstance(value, dict):
        return sum(len(k.encode()) + text_bytes(v) for k, v in value.items())
    return 0


def normalize(data, request, state, credential, enabled):
    """Return bounded redacted data and its distinct original-response byte commitment."""
    body = parse_json(data) if data else {}
    if not data and not request.operation.endswith("_delete"):
        raise ProviderFailure("empty_provider_response")
    json.dumps(body, allow_nan=False)
    if text_bytes(body) > request.max_text_bytes:
        raise ProviderFailure("response_text_byte_limit")
    ids = identities(body, request)
    clean = protect(body, credential)
    if clean != body and protect(ids, credential) != ids:
        raise ProviderFailure("credential_bearing_provider_identity")
    clips, rejections = (clip_results(clean, request) if request.operation == "search_text_image_composed_entity" else ([], []))
    status = remote_status(body, request.operation)
    if rejections:
        status = "partial"
    provider_status = body.get("status")
    if provider_status is not None and not isinstance(provider_status, str):
        raise ProviderFailure("invalid_provider_status")
    return TwelveLabsResponse(operation=request.operation, status=status, enabled=enabled,
        request_sha256=state["request_sha256"], ids=ids, provider_status=protect(provider_status, credential),
        provider_data=clean, provider_response_sha256=digest(data), observed_at=datetime.now(timezone.utc).isoformat(),
        clips=clips, rejections=rejections, media=state["media"], execution=state["execution"]).model_dump(mode="json")
