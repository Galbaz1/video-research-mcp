"""Response-only top-level projection and exact custom-schema text pagination.

Stored analysis remains complete. Source identities and complete citation/evidence
carriers are retained even when sparse fields are requested. Transcript pagination
supports the custom-schema top-level ``transcript`` string; offsets count Unicode
code points, not bytes, tokens, timestamps or transcript segments.
"""

from __future__ import annotations

from copy import deepcopy

MAX_TRANSCRIPT_OFFSET = 2**31 - 1
MAX_TRANSCRIPT_LIMIT = 10_000

_IDENTITY_FIELDS = frozenset(
    {
        "source",
        "sources",
        "source_id",
        "source_revision",
        "source_sha256",
        "source_hash",
        "source_freshness",
        "content_id",
        "cached",
        "cache_effects",
        "citations",
        "citation_id",
        "passage_id",
        "evidence",
        "evidence_packet",
        "claims",
        "lineage",
        "packet_id",
        "schema_version",
        "grounding",
        "grounding_metadata",
        "provenance",
        "coverage",
        "quality_report",
        "artifacts",
        "local_filepath",
        "screenshot_dir",
        "execution_usage",
    }
)


def _carries_evidence(value: object) -> bool:
    """Keep an entire custom field when it carries source or citation identity."""
    if isinstance(value, dict):
        return bool(_IDENTITY_FIELDS.intersection(value)) or any(
            _carries_evidence(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_carries_evidence(item) for item in value)
    return False


def validate_output_request(fields: list[str] | None, offset: int, limit: int | None) -> None:
    """Validate an output request before dynamic results or provider calls exist.

    Args:
        fields: Optional explicit top-level names; presence is checked after generation.
        offset: Original transcript code-point offset, from zero to MAX_TRANSCRIPT_OFFSET.
        limit: Optional page length, from one to MAX_TRANSCRIPT_LIMIT.

    Raises:
        ValueError: Names or pagination coordinates are invalid or unbounded.
    """
    if fields is not None:
        if not isinstance(fields, list) or any(
            type(name) is not str or not name for name in fields
        ):
            raise ValueError("fields must be a list of nonempty top-level names")
        if len(fields) != len(set(fields)):
            raise ValueError("fields must not contain duplicate top-level names")
    if type(offset) is not int or not 0 <= offset <= MAX_TRANSCRIPT_OFFSET:
        raise ValueError(f"transcript_offset must be an integer from 0 to {MAX_TRANSCRIPT_OFFSET}")
    if limit is None:
        if offset:
            raise ValueError("Nonzero transcript_offset requires transcript_limit")
    elif type(limit) is not int or not 1 <= limit <= MAX_TRANSCRIPT_LIMIT:
        raise ValueError(f"transcript_limit must be an integer from 1 to {MAX_TRANSCRIPT_LIMIT}")


def _transcript_page(result: dict, offset: int, limit: int) -> tuple[str, dict]:
    """Return a stable page; an offset at/past the end is a finished empty page."""
    transcript = result.get("transcript")
    if not isinstance(transcript, str):
        raise ValueError("Pagination requires a top-level transcript string")
    if "transcript_page" in result:
        raise ValueError("transcript_page is reserved for response pagination metadata")
    text = transcript[offset : offset + limit]
    end = offset + len(text)
    prefix_omitted = min(offset, len(transcript))
    remaining = max(len(transcript) - end, 0)
    return text, {
        "offset": offset,
        "limit": limit,
        "returned": len(text),
        "total": len(transcript),
        "next_offset": end if remaining else None,
        "truncated": bool(prefix_omitted or remaining),
        "prefix_omitted": prefix_omitted,
        "remaining": remaining,
        "unit": "unicode_codepoints",
    }


def project_output(
    result: dict,
    *,
    fields: list[str] | None = None,
    transcript_offset: int = 0,
    transcript_limit: int | None = None,
) -> dict:
    """Create a detached response view while preserving complete evidence carriers.

    Args:
        result: Full original JSON analysis, before any response projection.
        fields: Explicit top-level fields; None keeps every field. Source/citation
            fields and custom nested evidence carriers are automatically included.
        transcript_offset: Original string code-point offset, inclusive.
        transcript_limit: Bounded page length; None leaves transcript unchanged.

    Returns:
        Independent selected data. Pagination includes transcript and transcript_page
        even when omitted from fields. ``truncated`` indicates any omitted original
        text; ``prefix_omitted`` and ``remaining`` count excluded code points.
        ``next_offset`` is None when the suffix is exhausted, including past-end offsets.
        A sparse request also reports its requested/returned fields in output_view.

    Raises:
        ValueError: A request is invalid, selected fields are absent, or pagination
            cannot operate on an unambiguous top-level transcript string.
    """
    validate_output_request(fields, transcript_offset, transcript_limit)
    if not isinstance(result, dict):
        raise ValueError("Response projection requires a dict result")
    if fields is not None and any(name not in result for name in fields):
        raise ValueError("Selected fields must exist as top-level result names")
    if fields is not None and "output_view" in result:
        raise ValueError("output_view is reserved for response projection metadata")
    page = (
        None
        if transcript_limit is None
        else _transcript_page(result, transcript_offset, transcript_limit)
    )
    selected = set(result) if fields is None else set(fields)
    selected.update(
        name
        for name, value in result.items()
        if name in _IDENTITY_FIELDS or _carries_evidence(value)
    )
    view = {
        name: deepcopy(value)
        for name, value in result.items()
        if name in selected and not (page is not None and name == "transcript")
    }
    if page is not None:
        view["transcript"], view["transcript_page"] = page
    if fields is not None:
        view["output_view"] = {
            "requested_fields": fields.copy(),
            "returned_fields": [*view, "output_view"],
            "method": "top_level_fields_preserving_provenance",
        }
    return view
