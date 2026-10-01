"""Bounded provider normalization, privacy and inert source representations."""

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import quote, quote_plus, unquote, unquote_plus

from .models.search_provider import ExtractedPage, SearchHit, SearchProviderError, source_url
from .redaction import redact_text
from .url_policy import UrlPolicyError


class ProviderFailure(ValueError):
    """A fixed reason code without arbitrary upstream diagnostic content."""

    def __init__(self, code, category="SCHEMA_VALIDATION_FAILED"):
        super().__init__(code)
        self.code, self.category = code, category


def digest(data: bytes) -> str:
    """Commit exact bytes, including representations withheld after failure."""
    return hashlib.sha256(data).hexdigest()


def protect(value, credential):
    """Remove selected secrets even inside words, including both URL encodings."""
    if isinstance(value, str):
        if credential:
            for secret in {credential, quote(credential, safe=""), quote_plus(credential)}:
                value = value.replace(secret, "[redacted]")
            if credential in unquote(value) or credential in unquote_plus(value):
                value = "[redacted]"
        return redact_text(value)
    if isinstance(value, dict):
        return {protect(k, credential): protect(v, credential) for k, v in value.items()}
    if isinstance(value, list):
        return [protect(v, credential) for v in value]
    return value


def parse_json(data):
    """Require a finite JSON object rather than accepting NaN or permissive fallback."""
    def invalid(_value):
        raise ProviderFailure("nonfinite_json")

    value = json.loads(data.decode("utf-8", errors="strict"), parse_constant=invalid)
    if not isinstance(value, dict):
        raise ProviderFailure("response_not_object")
    return value


def error_result(error, operation, state):
    """Retain failed/cancelled attempt state without echoing upstream exceptions."""
    code, category = "provider_result_failed", "SCHEMA_VALIDATION_FAILED"
    if isinstance(error, ProviderFailure):
        code, category = error.code, error.category
    elif isinstance(error, UrlPolicyError):
        code, category = "source_url_policy_refused", "URL_POLICY_BLOCKED"
    elif isinstance(error, PermissionError):
        code, category = "configuration_or_authority_missing", "PERMISSION_DENIED"
    elif isinstance(error, asyncio.CancelledError):
        code, category = "operation_cancelled_outcome_unknown", "CANCELLED"
    elif isinstance(error, TimeoutError):
        code, category = "operation_deadline_outcome_unknown", "NETWORK_ERROR"
    for call in state["execution"]["calls"]:
        if call["status"] == "attempted":
            call["status"] = "interrupted_unknown" if isinstance(error, (TimeoutError, asyncio.CancelledError)) else "failed_unknown"
        if call.get("result_status") == "pending":
            call["result_status"] = "failed"
    return SearchProviderError(error=code, category=category,
        hint="Inspect the retained operation; no automatic retry or alternate provider is performed",
        operation=operation, backend=state["backend"], request_sha256=state["request_sha256"],
        rejections=[{"index": 0, "code": code}], execution=state["execution"]).model_dump(mode="json")


def normalize_search(body, backend, request, credential):
    """Keep every bounded result or explicit rejection without slicing populations."""
    array = "organic" if backend == "serper" else "results"
    rows = body.get(array)
    if not isinstance(rows, list) or len(rows) > request.num_results:
        raise ProviderFailure("result_population_invalid_or_over_limit")
    url_key = "link" if backend in {"serper", "serply"} else "url"
    text_key = {"serper": "snippet", "serply": "description", "tavily": "content", "exa": "text"}[backend]
    date_key = {"serper": "date", "serply": "date", "tavily": "published_date", "exa": "publishedDate"}[backend]
    hits, rejections, observed_text = [], [], 0
    for index, row in enumerate(rows):
        if isinstance(row, dict):
            observed_text += sum(len(row[k].encode()) for k in ("title", text_key, date_key) if isinstance(row.get(k), str))
        if observed_text > request.max_text_bytes:
            raise ProviderFailure("returned_text_byte_limit")
        try:
            if not isinstance(row, dict) or not isinstance(row.get(url_key), str):
                raise ValueError("missing URL")
            source_url(row[url_key])
            title, text, date = (row.get(k) for k in ("title", text_key, date_key))
            if any(value is not None and not isinstance(value, str) for value in (title, text, date)):
                raise ValueError("invalid observed text")
            clean = protect(text, credential) if text is not None else None
            hits.append(SearchHit(url=protect(row[url_key], credential), title=protect(title, credential),
                text=clean, date=protect(date, credential), text_sha256=digest(clean.encode()) if clean is not None else None,
                metadata=protect({k: v for k, v in row.items() if k not in {url_key, "title", text_key, date_key}}, credential)))
        except (ValueError, TypeError):
            rejections.append({"index": index, "code": "unsafe_or_malformed_result"})
    return hits, rejections, protect({k: v for k, v in body.items() if k != array}, credential)


def _extract_identity_matches(row, backend, url):
    """Use Tavily's URL contract and refuse conflicting Exa URL/ID observations."""
    if not isinstance(row, dict):
        return False
    if backend == "tavily":
        return row.get("url") == url
    observed = [row[key] for key in ("url", "id") if row.get(key) is not None]
    if url not in observed:
        return False
    if any(value != url for value in observed):
        raise ProviderFailure("contradictory_extraction_identity")
    return True


def provider_page(body, backend, url):
    """Match the requested URL, preserving per-URL failure/status semantics."""
    if backend == "serply":
        return body.decode("utf-8", errors="strict"), None, {}
    value = parse_json(body)
    if backend == "serper":
        if value.get("url", url) != url:
            raise ProviderFailure("provider_returned_other_url")
        text = value.get("markdown") or value.get("text")
        return text, value.get("title"), {k: v for k, v in value.items() if k not in {"markdown", "text", "title"}}
    rows, statuses = value.get("results"), value.get("statuses", [])
    failures = value.get("failed_results", [])
    if not isinstance(rows, list) or not isinstance(statuses, list) or not isinstance(failures, list):
        raise ProviderFailure("extract_population_invalid")
    matches = [r for r in rows if _extract_identity_matches(r, backend, url)]
    failed = [r for r in failures if isinstance(r, dict) and r.get("url") == url]
    matching_statuses = [r for r in statuses if backend == "exa" and _extract_identity_matches(r, backend, url)]
    if failed or any(s.get("status") != "success" for s in matching_statuses):
        raise ProviderFailure("provider_reported_requested_url_failure")
    if len(matches) != 1 or (backend == "exa" and len(matching_statuses) > 1):
        raise ProviderFailure("requested_url_missing_or_ambiguous")
    row = matches[0]
    text_key = "text" if backend == "exa" else "raw_content"
    metadata = {k: v for k, v in value.items() if k != "results"}
    metadata["matched_result"] = {k: v for k, v in row.items() if k not in {text_key, "title"}}
    return row.get(text_key), row.get("title"), metadata


def page_result(url, text, title, mime, credential, *, direct=False, final_url=None):
    """Expose both raw representation and redacted content commitments honestly."""
    if not isinstance(text, str) or not text or (title is not None and not isinstance(title, str)):
        raise ProviderFailure("extracted_content_missing_or_invalid")
    raw, clean = text.encode(), protect(text, credential)
    observed = datetime.now(timezone.utc).isoformat()
    return ExtractedPage(url=protect(url, credential), final_url=protect(final_url, credential),
        title=protect(title, credential), content=clean, fetched_at=observed,
        page_fetched_at=observed if direct else None, content_type=mime,
        representation="direct_response" if direct else "provider_returned",
        representation_sha256=digest(raw), content_sha256=digest(clean.encode()),
        bytes=len(raw), returned_bytes=len(clean.encode()), redactions_applied=clean != text,
        original_page_bytes_verified=direct, remote_redirects_verified=direct)
