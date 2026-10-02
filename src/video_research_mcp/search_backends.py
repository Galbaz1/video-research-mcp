"""Four explicit optional search services with one authenticated request each."""

import asyncio
import json
import os
from urllib.parse import urlencode

from .config import get_config
from .models.search_provider import SearchExecution, SearchProviderRequest, SearchProviderResponse
from .search_provider_results import (ProviderFailure, digest, error_result, normalize_search, protect)
from .vision_http import exchange

PRIORITY = ("serper", "tavily", "exa", "serply")
KEYS = {"serper": "SERPER_API_KEY", "tavily": "TAVILY_API_KEY", "exa": "EXA_API_KEY", "serply": "SERPLY_API_KEY"}


def _credential(backend):
    value = os.getenv(KEYS[backend], "").strip()
    return "" if value.startswith("$") or value.lower() == "your-api-key-here" else value


def select_backend(backend):
    """Select only enabled credentials; never borrow keys or fall back after failure."""
    enabled = tuple(get_config().search_backends)
    if backend == "direct":
        return "direct", "", enabled
    if backend == "auto":
        backend = next((name for name in PRIORITY if name in enabled and _credential(name)), None)
        if backend is None:
            raise PermissionError("No enabled credential-ready search backend")
    if backend not in enabled:
        raise PermissionError("Selected search backend is not enabled")
    credential = _credential(backend)
    if not credential:
        raise PermissionError("Selected search backend credential is missing")
    return backend, credential, enabled


def check_selection(request, selected):
    """Reject concurrent account or configured provider changes before promotion."""
    if select_backend(request.backend) != selected:
        raise PermissionError("Selected search account/configuration changed")


def operation_state():
    """Keep attempted operation receipts available to success and failure models."""
    return {"backend": None, "request_sha256": None,
            "execution": SearchExecution().model_dump(mode="json")}


def bind_request(request, selected, state):
    """Commit actual selection and credential scope without exposing key material."""
    backend, credential, enabled = selected
    state["backend"] = backend
    binding = {"request": request.model_dump(mode="json"), "backend": backend,
               "credential_sha256": digest(credential.encode()), "enabled": enabled}
    state["request_sha256"] = digest(json.dumps(binding, sort_keys=True, allow_nan=False).encode())


def service_request(backend, operation, value, credential, count=5):
    """Construct the exact four fixed-origin schemas; source URLs remain body data."""
    if backend == "serper":
        url = "https://google.serper.dev/" + ("search" if operation == "search" else "scrape")
        body = {"q": value, "gl": "us", "hl": "en", "location": "United States", "num": count} if operation == "search" else {"url": value, "includeMarkdown": True}
        headers = {"X-API-KEY": credential}
    elif backend == "tavily":
        url = "https://api.tavily.com/" + ("search" if operation == "search" else "extract")
        body = {"query": value, "search_depth": "basic", "max_results": count, "include_answer": False} if operation == "search" else {"urls": [value], "format": "markdown"}
        headers = {"Authorization": "Bearer " + credential}
    elif backend == "exa":
        url = "https://api.exa.ai/" + ("search" if operation == "search" else "contents")
        body = {"query": value, "numResults": count, "contents": {"text": {"maxCharacters": 1000}}} if operation == "search" else {"urls": [value], "text": {"maxCharacters": 8000}}
        headers = {"x-api-key": credential}
    else:
        headers = {"X-Api-Key": credential}
        if operation == "search":
            url = "https://api.serply.io/v1/search/?" + urlencode({"q": value, "num": count, "hl": "en", "gl": "us"})
            return url, headers, b"", "GET"
        url, body = "https://api.serply.io/v1/request", {"url": value, "response_type": "markdown"}
    headers["Content-Type"] = "application/json"
    return url, headers, json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(), "POST"


async def call_service(request, selected, operation, value, state):
    """Retain attempt/hash/status even when output parsing or HTTP status fails."""
    check_selection(request, selected)
    backend, credential, _enabled = selected
    url, headers, content, method = service_request(backend, operation, value, credential,
                                                   getattr(request, "num_results", 5))
    call = {"kind": operation, "backend": backend, "status": "attempted", "result_status": "pending",
            "request_body_sha256": digest(content), "physical_requests": None,
            "physical_request_upper_bound": 1, "usage": None}
    execution = state["execution"]
    execution["calls"].append(call)
    execution.update(provider_requests_attempted=1, physical_requests=None, physical_request_upper_bound=1)
    status, data = await exchange(url, headers=headers, content=content, method=method)
    call.update(status="response_received", http_status=status, received_bytes=len(data),
                response_sha256=digest(data))
    check_selection(request, selected)
    if len(data) > request.max_response_bytes:
        raise ProviderFailure("response_byte_limit")
    if status != 200:
        category = "API_PERMISSION_DENIED" if status in {401, 403} else "API_QUOTA_EXCEEDED" if status == 429 else "NETWORK_ERROR"
        raise ProviderFailure(f"provider_http_{status}", category)
    return data


async def search_provider(request: SearchProviderRequest) -> dict:
    """Execute or plan one optional-provider query with complete result accounting."""
    from .search_provider_results import parse_json

    state = operation_state()
    try:
        request = SearchProviderRequest.model_validate(request)
        selected = select_backend(request.backend)
        bind_request(request, selected, state)
        backend, credential, _enabled = selected
        hits, rejections, metadata = [], [], {}
        if not request.dry_run:
            if not request.authorize_submission:
                raise PermissionError("Search requires explicit submission authorization")
            async with asyncio.timeout(request.timeout_seconds):
                data = await call_service(request, selected, "search", request.query, state)
                hits, rejections, metadata = normalize_search(parse_json(data), backend, request, credential)
                if sum(len((v or "").encode()) for h in hits for v in (h.title, h.text, h.date)) > request.max_text_bytes:
                    raise ProviderFailure("returned_text_byte_limit")
                state["execution"]["calls"][-1]["result_status"] = "retained"
        return SearchProviderResponse(operation="search", status="planned" if request.dry_run else "partial" if rejections else "complete",
            backend=backend, request_sha256=state["request_sha256"], query=protect(request.query, credential),
            results=hits, rejections=rejections, metadata=metadata, execution=state["execution"]).model_dump(mode="json")
    except (Exception, asyncio.CancelledError) as error:
        return error_result(error, "search", state)
