"""One explicit public frame upload, exact readback and bounded Serper Lens request."""

import asyncio
from datetime import datetime, timezone
import json

from .models.reverse_search import FramePublication, ReverseFrameError, ReverseFrameRequest, ReverseFrameResponse
from .models.search_provider import SearchExecution
from .reverse_frame_sources import candidates, frame_bytes, publication_url, verify_capture
from .search_backends import select_backend
from .search_provider_results import ProviderFailure, digest, parse_json
from .vision_http import exchange


def multipart(image):
    """Send only the selected PNG with a constant filename and byte-boundary commitment."""
    boundary = "vrm-frame-" + digest(image)
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="files[]"; filename="frame.png"\r\n'
            'Content-Type: image/png\r\n\r\n').encode() + image + f"\r\n--{boundary}--\r\n".encode()
    return body, {"Content-Type": "multipart/form-data; boundary=" + boundary}


async def transfer(kind, url, content, headers, state, request, selected):
    """Commit one attempt before transport and retain unknown publication outcomes on failure."""
    if select_backend("serper") != selected:
        raise PermissionError("Selected Serper account/configuration changed")
    execution = state["execution"]
    call = {"kind": kind, "status": "attempted", "request_body_sha256": digest(content),
            "physical_requests": None, "physical_request_upper_bound": 1}
    execution["calls"].append(call)
    execution.update(physical_requests=None, physical_request_upper_bound=len(execution["calls"]))
    if kind == "lens":
        execution["provider_requests_attempted"] += 1
    else:
        execution["direct_requests_reserved"] += 1
    if kind == "public_upload":
        state["publication"].update(status="outcome_unknown",
            attempted_at=datetime.now(timezone.utc).isoformat(),
            submitted_image_sha256=state["query"].frame_sha256,
            submitted_image_bytes=state["query"].frame_bytes)
    status, data = await exchange(url, headers=headers, content=content, method="GET" if kind == "readback" else "POST")
    call.update(status="response_received", http_status=status, response_sha256=digest(data), received_bytes=len(data))
    if select_backend("serper") != selected:
        raise PermissionError("Selected Serper account/configuration changed")
    if status != 200:
        category = "API_PERMISSION_DENIED" if status in {401, 403} else "API_QUOTA_EXCEEDED" if status == 429 else "NETWORK_ERROR"
        raise ProviderFailure(f"{kind}_http_{status}", category)
    if len(data) > request.max_response_bytes:
        raise ProviderFailure("reverse_frame_response_byte_limit")
    return data


async def upload_and_search(image, request, selected, state):
    """Verify hosted query bytes before disclosing the public URL to Lens; never retry."""
    content, headers = multipart(image)
    data = await transfer("public_upload", "https://uguu.se/upload", content, headers, state, request, selected)
    url = publication_url(parse_json(data), selected[1], len(image))
    state["publication"].update(status="url_received", url=url,
        acknowledged_at=datetime.now(timezone.utc).isoformat())
    hosted = await transfer("readback", url, b"", {}, state, request, selected)
    state["publication"]["hosted_response_sha256"] = digest(hosted)
    if hosted != image:
        raise ProviderFailure("hosted_query_bytes_differ")
    state["publication"]["status"] = "bytes_verified"
    body = json.dumps({"url": url, "gl": "us", "hl": "en"}, separators=(",", ":")).encode()
    data = await transfer("lens", "https://google.serper.dev/lens", body,
        {"X-API-KEY": selected[1], "Content-Type": "application/json"}, state, request, selected)
    return candidates(parse_json(data), request, selected[1])


def failed(error, state):
    """Withhold source-controlled exception text while retaining all side-effect receipts."""
    code, category = "reverse_frame_invalid", "SCHEMA_VALIDATION_FAILED"
    if isinstance(error, ProviderFailure):
        code, category = error.code, error.category
    elif isinstance(error, PermissionError):
        code, category = "configuration_or_authority_missing", "PERMISSION_DENIED"
    elif isinstance(error, (asyncio.CancelledError, TimeoutError)):
        code, category = "interrupted_outcome_unknown", "CANCELLED" if isinstance(error, asyncio.CancelledError) else "NETWORK_ERROR"
    for call in state["execution"]["calls"]:
        if call["status"] == "attempted":
            call["status"] = "interrupted_unknown"
    return ReverseFrameError(error=code, category=category,
        hint="Inspect publication/attempt receipts; do not retry or assert entity identity automatically",
        query=state["query"], publication=state["publication"], execution=state["execution"]).model_dump(mode="json")


async def reverse_search(request: ReverseFrameRequest) -> dict:
    """Plan or run one point query; suggestions require separate appearance/text/context review."""
    state = {"query": None, "publication": FramePublication().model_dump(mode="json"),
             "execution": SearchExecution().model_dump(mode="json")}
    try:
        request = ReverseFrameRequest.model_validate(request)
        selected = select_backend("serper")
        if not request.dry_run and not (request.authorize_submission and request.authorize_public_upload):
            raise PermissionError("Explicit search and public PNG publication grants are required")
        async with asyncio.timeout(request.timeout_seconds):
            image, query = await frame_bytes(request)
            state["query"] = query
            binding = {"query": query.model_dump(mode="json"), "selected_account_sha256": digest(selected[1].encode()),
                       "enabled": selected[2],
                       "request_settings": request.model_dump(mode="json", exclude={"capture"})}
            commitment = digest(json.dumps(binding, sort_keys=True, allow_nan=False).encode())
            results, rejections, population = [], [], 0
            if not request.dry_run:
                results, rejections, population = await upload_and_search(image, request, selected, state)
                await verify_capture(request, query)
            return ReverseFrameResponse(status="planned" if request.dry_run else "partial" if rejections else "complete",
                query=query, request_sha256=commitment, publication=state["publication"], results=results,
                rejections=rejections, returned_population=population, execution=state["execution"]).model_dump(mode="json")
    except (Exception, asyncio.CancelledError) as error:
        return failed(error, state)
