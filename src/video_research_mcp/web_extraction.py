"""One authorized checked webpage or explicitly selected provider representation."""

import asyncio
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .models.search_provider import SearchProviderResponse, WebExtractRequest
from .search_backends import bind_request, call_service, check_selection, operation_state, select_backend
from .search_provider_results import ProviderFailure, digest, error_result, page_result, protect, provider_page
from .url_policy import checked_response, validate_url


class _Title(HTMLParser):
    """Read bounded HTML title text without interpreting scripts or instructions."""

    def __init__(self):
        super().__init__()
        self.active, self.parts, self.size = False, [], 0

    def handle_starttag(self, tag, attrs):
        self.active = tag == "title" or self.active

    def handle_endtag(self, tag):
        if tag == "title":
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.size += len(data.encode())
            if self.size > 4096:
                raise ProviderFailure("title_byte_limit")
            self.parts.append(data)


def _headers(response, request):
    """Reject unsupported bodies before any decompression or response buffering."""
    value = response.headers.get("content-type", "").lower()
    mime, *parameters = value.split(";")
    mime = mime.strip()
    if mime not in {"text/plain", "text/html", "application/json"} and not (mime.startswith("application/") and mime.endswith("+json")):
        raise ProviderFailure("unsupported_page_content_type", "FILE_UNSUPPORTED")
    if response.headers.get("content-encoding", "identity").lower() != "identity":
        raise ProviderFailure("compressed_direct_page_unsupported")
    for parameter in parameters:
        if parameter.strip().startswith("charset=") and parameter.strip()[8:].strip(' "') not in {"utf-8", "utf8"}:
            raise ProviderFailure("page_charset_not_utf8")
    length = response.headers.get("content-length")
    if length is not None and (not length.isdecimal() or int(length) > min(request.max_response_bytes, request.max_text_bytes)):
        raise ProviderFailure("page_content_length_limit")
    return mime


async def _direct(request, hosts, state):
    """Keep the fixed redirect reservation separate from measured decoded bytes."""
    call = {"kind": "direct_fetch", "status": "attempted", "result_status": "pending",
            "physical_requests": None, "physical_request_upper_bound": 6, "received_bytes": 0}
    state["execution"]["calls"].append(call)
    state["execution"].update(direct_requests_reserved=6, physical_requests=None, physical_request_upper_bound=6)
    async with checked_response(request.url, allowed_hosts=hosts) as response:
        call["http_status"] = response.status_code
        mime = _headers(response, request)
        data, committed = bytearray(), None
        async for chunk in response.aiter_bytes(chunk_size=min(65536, request.max_response_bytes + 1)):
            call["received_bytes"] += len(chunk)
            if len(data) + len(chunk) > min(request.max_response_bytes, request.max_text_bytes):
                raise ProviderFailure("page_body_byte_limit")
            data.extend(chunk)
        committed = bytes(data)
        call.update(status="response_received", response_sha256=digest(committed))
        text = committed.decode("utf-8", errors="strict")
        parser = _Title()
        if mime == "text/html":
            parser.feed(text)
        return page_result(request.url, text, "".join(parser.parts) or None, mime, "",
                           direct=True, final_url=str(response.url)), {}


async def _provider(request, selected, state):
    """Check source URL policy without claiming control of a remote service's fetch."""
    call = {"kind": "source_url_validation", "status": "attempted", "result_status": "pending",
            "physical_requests": 0, "physical_request_upper_bound": 0}
    state["execution"]["calls"].append(call)
    await validate_url(request.url)
    call.update(status="validated", result_status="retained")
    check_selection(request, selected)
    backend, credential, _enabled = selected
    data = await call_service(request, selected, "extract", request.url, state)
    text, title, metadata = provider_page(data, backend, request.url)
    if not isinstance(text, str) or len(text.encode()) > request.max_text_bytes:
        raise ProviderFailure("extracted_text_missing_or_over_limit")
    page = page_result(request.url, text, title, "text/markdown", credential)
    return page, protect(metadata, credential)


async def extract_web(request: WebExtractRequest) -> dict:
    """Return a typed one-URL plan/result or an observable failed/cancelled outcome."""
    state = operation_state()
    try:
        request = WebExtractRequest.model_validate(request)
        selected = select_backend(request.backend)
        bind_request(request, selected, state)
        backend, credential, _enabled = selected
        hosts = set(request.allowed_domains) or {urlsplit(request.url).hostname}
        if urlsplit(request.url).hostname not in hosts:
            raise ProviderFailure("source_host_not_allowed", "URL_POLICY_BLOCKED")
        page, metadata = None, {"remote_provider_page_peer_verified": False}
        if not request.dry_run:
            if not request.authorize_submission:
                raise PermissionError("Page acquisition requires explicit authorization")
            async with asyncio.timeout(request.timeout_seconds):
                page, observed = await _direct(request, hosts, state) if backend == "direct" else await _provider(request, selected, state)
                if page.returned_bytes > request.max_text_bytes:
                    raise ProviderFailure("returned_text_byte_limit")
                check_selection(request, selected)
                metadata.update(observed)
                state["execution"]["calls"][-1]["result_status"] = "retained"
        return SearchProviderResponse(operation="extract", status="planned" if request.dry_run else "complete",
            backend=backend, request_sha256=state["request_sha256"], url=protect(request.url, credential),
            page=page, metadata=metadata, execution=state["execution"]).model_dump(mode="json")
    except (Exception, asyncio.CancelledError) as error:
        return error_result(error, "extract", state)
