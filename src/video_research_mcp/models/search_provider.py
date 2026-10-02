"""Explicit optional search and raw page extraction contracts."""

from ipaddress import ip_address
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from .image_edit import Digest, Number, StrictModel
from ..errors import ToolError

Provider = Literal["serper", "tavily", "exa", "serply"]
Backend = Literal["direct", "serper", "tavily", "exa", "serply"]


def source_url(value: str) -> str:
    """Reject unsafe syntax and literal private targets without performing DNS."""
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None
            or "#" in value or any(ord(c) < 33 or ord(c) == 127 for c in value)):
        raise ValueError("Source URLs require HTTPS without userinfo, fragments or control characters")
    parsed.port  # Reject malformed port syntax before any transport.
    try:
        address = ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and (not address.is_global or address.is_multicast or address.is_reserved):
        raise ValueError("Literal source targets must be public")
    return value


class SourceLimits(StrictModel):
    """Bound one invocation without retry or implicit provider selection authority."""

    dry_run: Annotated[bool, Field(strict=True)] = True
    authorize_submission: Annotated[bool, Field(strict=True)] = False
    timeout_seconds: Annotated[Number, Field(gt=0, le=120)] = 120
    max_response_bytes: Annotated[int, Field(strict=True, ge=1, le=256 * 1024)] = 256 * 1024
    max_text_bytes: Annotated[int, Field(strict=True, ge=1, le=128 * 1024)] = 128 * 1024


class SearchProviderRequest(SourceLimits):
    """One bounded query; auto only considers enabled, credential-ready providers."""

    query: Annotated[str, Field(strict=True, min_length=2, max_length=8192)]
    backend: Literal["auto", "serper", "tavily", "exa", "serply"] = "auto"
    num_results: Annotated[int, Field(strict=True, ge=1, le=10)] = 5


class WebExtractRequest(SourceLimits):
    """One source URL; provider representations do not attest remote page bytes."""

    url: Annotated[str, Field(strict=True, min_length=1, max_length=2048)]
    backend: Literal["direct", "auto", "serper", "tavily", "exa", "serply"] = "direct"
    allowed_domains: Annotated[list[Annotated[str, Field(pattern=r"^[a-z0-9.-]{1,253}$")]], Field(max_length=8)] = []

    @model_validator(mode="after")
    def safe_source(self):
        """Check syntax in dry plans; defer DNS to explicitly authorized execution."""
        source_url(self.url)
        return self


class ProviderRejection(StrictModel):
    """Retain a rejected result without returning its arbitrary source body."""

    index: Annotated[int, Field(strict=True, ge=0)]
    code: str


class SearchHit(StrictModel):
    """Untrusted provider observations; returned links have not undergone DNS checks."""

    url: str
    title: str | None
    text: str | None
    date: str | None
    text_sha256: Digest | None
    metadata: dict
    url_dns_verified: Literal[False] = False


class ExtractedPage(StrictModel):
    """Bind observed representation bytes separately from redacted returned content."""

    url: str
    final_url: str | None
    title: str | None
    content: str
    fetched_at: str
    page_fetched_at: str | None
    content_type: str
    representation: Literal["direct_response", "provider_returned"]
    representation_sha256: Digest
    content_sha256: Digest
    bytes: Annotated[int, Field(strict=True, ge=0)]
    returned_bytes: Annotated[int, Field(strict=True, ge=0)]
    redactions_applied: bool
    original_page_bytes_verified: bool
    remote_redirects_verified: bool


class SearchExecution(StrictModel):
    """Record attempts and reservations without inventing wire or currency usage."""

    calls: list[dict] = []
    provider_requests_attempted: Annotated[int, Field(strict=True, ge=0)] = 0
    direct_requests_reserved: Annotated[int, Field(strict=True, ge=0)] = 0
    physical_requests: Annotated[int | None, Field(strict=True, ge=0)] = 0
    physical_request_upper_bound: Annotated[int, Field(strict=True, ge=0)] = 0
    cost_usd: None = None
    charge_bound_verified: Literal[False] = False
    retries: Literal[0] = 0
    cache_used: Literal[False] = False


class SearchProviderResponse(StrictModel):
    """Typed dry/success/partial outcome retaining source and call denominators."""

    operation: Literal["search", "extract"]
    status: Literal["planned", "complete", "partial"]
    backend: Backend
    request_sha256: Digest
    query: str | None = None
    url: str | None = None
    results: Annotated[list[SearchHit], Field(max_length=10)] = []
    page: ExtractedPage | None = None
    rejections: Annotated[list[ProviderRejection], Field(max_length=10)] = []
    metadata: dict = {}
    execution: SearchExecution
    source_content_role: Literal["data"] = "data"
    factual_success: Literal[False] = False


class SearchProviderError(ToolError):
    """An inert failed/cancelled operation with known attempts and withheld bodies."""

    operation: Literal["search", "extract"]
    backend: Backend | None = None
    request_sha256: Digest | None = None
    rejections: list[ProviderRejection] = []
    execution: SearchExecution
