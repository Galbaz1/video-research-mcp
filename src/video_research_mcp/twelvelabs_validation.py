"""Validate selected current service inputs without inventing vendor DTOs."""

from pydantic import TypeAdapter

from .models.twelvelabs import Identifier

_ID = TypeAdapter(Identifier)
_REQUIRED = {
    "index_create": ("index_name", "models"),
    "indexed_asset_create": ("asset_id",),
    "search_text_image_composed_entity": ("index_id", "search_options"),
    "embedding_task_create": ("input_type", "model_name", "video"),
    "entity_collection_create": ("name",),
    "entity_create": ("name", "asset_ids"),
    "analysis_sync": ("video",),
    "analysis_task_create": ("video",),
}


def parameters_for(request):
    """Reject invalid controls and unsupported legacy inputs before any transmission."""
    value, operation = dict(request.parameters), request.operation
    if any(name not in value for name in _REQUIRED.get(operation, ())):
        raise ValueError("Selected route is missing required current parameters")
    if {"file", "query_media_file", "video_id", "api_key", "request_options"} & value.keys():
        raise ValueError("Use bounded local_file and current IDs; raw file/key/SDK controls are unsupported")
    if "page_limit" in value and (type(value["page_limit"]) is not int or not 1 <= value["page_limit"] <= 50):
        raise ValueError("TwelveLabs page_limit must be an integer from 1 to 50")
    if "asset_id" in value:
        _ID.validate_python(value["asset_id"])
    for name in ("name", "index_name", "model_name"):
        if name in value and (not isinstance(value[name], str) or not value[name].strip()):
            raise ValueError("Names must be explicit nonempty strings")
    if operation == "index_create" and (not isinstance(value["models"], list) or not value["models"]):
        raise ValueError("Index creation requires explicitly selected model objects")
    if operation == "entity_create":
        if not isinstance(value["asset_ids"], list) or not 1 <= len(value["asset_ids"]) <= 50:
            raise ValueError("Select one to fifty provider asset IDs")
        for asset_id in value["asset_ids"]:
            _ID.validate_python(asset_id)
    if operation in {"analysis_sync", "analysis_task_create"}:
        analysis_parameters(value, operation)
    if operation == "search_text_image_composed_entity":
        search_parameters(value, request.local_file)
    if operation == "embedding_task_create":
        if value["input_type"] != "video" or not isinstance(value["video"], dict):
            raise ValueError("This selected embedding contract requires an explicit video object")
        source = value["video"].get("media_source")
        if not isinstance(source, dict) or set(source) != {"url"}:
            raise ValueError("Select a current video media_source URL; legacy embedding inputs are unsupported")
    return value


def analysis_parameters(value, operation):
    """Use the inspected URL wire contract and bounded non-streaming analysis."""
    video = value["video"]
    if not isinstance(video, dict) or set(video) != {"type", "url"} or video["type"] != "url":
        raise ValueError("Select video={type:url,url:HTTPS}; unexpanded asset/base64 variants are unsupported")
    if "prompt" in value and "prompt_v2" in value:
        raise ValueError("Select prompt or prompt_v2, not both")
    if operation == "analysis_sync":
        if value.get("stream", False) is not False:
            raise ValueError("Only bounded stream=false analysis is supported")
        value["stream"] = False
    if "start_time" in value and "end_time" in value:
        start, end = value["start_time"], value["end_time"]
        if type(start) not in {int, float} or type(end) not in {int, float} or end - start < 1:
            raise ValueError("Selected analysis window must be at least one second")


def search_parameters(value, local_file):
    """Admit explicit text/image/composed/entity queries with a bounded population."""
    _ID.validate_python(value["index_id"])
    options = value["search_options"]
    if not isinstance(options, list) or not options or any(not isinstance(v, str) or not v for v in options):
        raise ValueError("Search requires explicit search_options strings")
    if not value.get("query_text") and not value.get("query_media_url") and local_file is None:
        raise ValueError("Search requires text, image URL(s) or one bounded local image")
    if "query_text" in value and not isinstance(value["query_text"], str):
        raise ValueError("Search text must be a string")
    if "query_media_url" in value:
        urls = value["query_media_url"]
        if not isinstance(urls, list) or not 1 <= len(urls) <= 10:
            raise ValueError("Select one to ten image URLs")
        if value.get("query_media_type") != "image":
            raise ValueError("Image URLs require query_media_type=image")
    value.setdefault("group_by", "clip")
    if value["group_by"] not in {"clip", "video"}:
        raise ValueError("Search group_by must be clip or video")
