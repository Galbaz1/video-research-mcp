"""Construct one fixed-origin request, including bounded explicitly selected media."""

import asyncio
import json
import threading
from urllib.parse import urlencode

import httpx

from .media_local_io import _open_regular
from .media_acquisition import _wait_worker
from .media_snapshot import checked_path
from .models.search_provider import source_url
from .search_provider_results import digest, protect
from .twelvelabs_routes import ROUTES
from .twelvelabs_validation import parameters_for

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
         ".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo",
         ".mkv": "video/x-matroska", ".webm": "video/webm"}


def fields(parameters):
    """Encode repeatable form/query fields without changing their selected values."""
    result = []
    for name, value in parameters.items():
        if not name or len(name) > 128 or any(c not in "abcdefghijklmnopqrstuvwxyz_0123456789." for c in name):
            raise ValueError("Invalid TwelveLabs parameter name")
        for item in value if isinstance(value, list) else [value]:
            text = json.dumps(item, allow_nan=False, ensure_ascii=False) if not isinstance(item, str) else item
            result.append((name, text))
            if len(result) > 128:
                raise ValueError("TwelveLabs form/query exceeds 128 parts")
    return result


def media_urls(parameters):
    """Check declared URL media inputs without claiming the provider's DNS or fetch behavior."""
    result = []
    for name, value in parameters.items():
        if name in {"url", "query_media_url", "video_url"}:
            for url in value if isinstance(value, list) else [value]:
                if not isinstance(url, str):
                    raise ValueError("Media URL must be a string")
                result.append(source_url(url))
        elif isinstance(value, dict):
            result.extend(media_urls(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    result.extend(media_urls(item))
    return result


def local_media(request, cancelled):
    """Hash the same fenced bounded bytes supplied to the multipart request."""
    if request.local_file is None:
        return None, None
    path = checked_path(request.local_file)
    suffix = path.suffix.lower()
    if suffix not in _MIME or (request.operation == "search_text_image_composed_entity" and not _MIME[suffix].startswith("image/")):
        raise ValueError("Select a supported video/image extension; search accepts images only")
    with _open_regular(path) as stream:
        parts, size = [], 0
        while size <= request.max_media_bytes:
            if cancelled.is_set():
                raise TimeoutError("Local media preparation canceled")
            chunk = stream.read(min(64 * 1024, request.max_media_bytes + 1 - size))
            if not chunk:
                break
            parts.append(chunk)
            size += len(chunk)
    body = b"".join(parts)
    if not body or len(body) > request.max_media_bytes:
        raise ValueError("Local media is empty or exceeds its byte limit")
    actual = digest(body)
    if actual != request.expected_source_sha256:
        raise ValueError("Local media differs from expected source SHA256")
    return body, {"source_sha256": actual, "bytes": len(body), "media_type": _MIME[suffix], "extension": suffix,
                  "admission_bytes_verified": True,
                  "remote_bytes_verified": False, "decoded_media_verified": False}


def request_bytes(request, credential, cancelled):
    """Return exact bounded wire bytes and admitted media without following source URLs."""
    method, path, format_ = ROUTES[request.operation]
    parameters = parameters_for(request)
    urls = media_urls(parameters)
    disclosure = request.operation in {"asset_create", "indexed_asset_create", "embedding_task_create",
                                       "analysis_sync", "analysis_task_create", "entity_create"}
    if not request.dry_run and (disclosure or request.local_file is not None or urls) and not request.authorize_media_transfer:
        raise PermissionError("Explicit local or URL media-transfer authorization is required")
    media, receipt = local_media(request, cancelled)
    if receipt is None and urls:
        receipt = {"source_urls": urls, "admission_bytes_verified": False,
                   "remote_bytes_verified": False, "provider_fetch_bounds_verified": False}
    url = "https://api.twelvelabs.io" + path.format(**request.ids)
    headers = {"x-api-key": credential}
    body = b""
    if format_ == "multipart/form-data":
        if request.operation == "asset_create":
            if (media is None) == (parameters.get("url") is None):
                raise ValueError("Asset creation requires exactly one local file or URL")
            selected_method = "direct" if media is not None else "url"
            if parameters.get("method", selected_method) != selected_method:
                raise ValueError("Asset method conflicts with the selected media source")
            parameters["method"] = selected_method
            if "url" in parameters and not isinstance(parameters["url"], str):
                raise ValueError("Asset creation requires one URL string")
        elif media is not None:
            if parameters.get("query_media_url"):
                raise ValueError("Choose local image or image URLs for one search")
            if parameters.get("query_media_type", "image") != "image":
                raise ValueError("Local query_media_type must be image")
            parameters["query_media_type"] = "image"
        parts = [(name, (None, value)) for name, value in fields(parameters)]
        if media is not None:
            name = "file" if request.operation == "asset_create" else "query_media_file"
            parts.append((name, ("media" + receipt["extension"], media, receipt["media_type"])))
        encoded = httpx.Request(method, url, files=parts)
        body, headers["Content-Type"] = encoded.read(), encoded.headers["content-type"]
    elif format_ == "application/json":
        body = json.dumps(parameters, allow_nan=False, ensure_ascii=False, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    elif format_ == "query" and parameters:
        url += "?" + urlencode(fields(parameters))
    elif format_ == "none" and parameters:
        raise ValueError("Selected route accepts no body or query parameters")
    if len(body) > request.max_media_bytes + 128 * 1024 or protect(parameters, credential) != parameters:
        raise ValueError("Request exceeds its byte bound or contains credential-bearing data")
    return method, url, headers, body, receipt


async def prepare_wire(request, credential):
    """Join cooperative local preparation before returning a canceled invocation."""
    cancelled = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(request_bytes, request, credential, cancelled))
    async with asyncio.timeout(request.timeout_seconds):
        return await _wait_worker(task, cancelled)
