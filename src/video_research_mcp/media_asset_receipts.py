"""Bound serialized asset histories and page metadata before admission or decoding."""

from __future__ import annotations

import hashlib
import json
import sqlite3

from . import redaction
from .media_identity import valid_digest

MAX_ASSET_RECEIPTS_BYTES = 64 * 1024
MAX_PAGE_METADATA_BYTES = 1024 * 1024
MAX_PAGE_OUTPUT_BYTES = 1024 * 1024


def serialized_bytes(value) -> int:
    """Measure bounded public dictionaries using conservative default JSON spacing."""
    return len(json.dumps(value, allow_nan=False).encode())


def metadata_stub(row: sqlite3.Row) -> dict:
    """Retain bounded row identity while reserving space for the complete page."""
    return {
        "asset_id": row["digest"],
        "bytes": row["size"],
        "state": "unknown",
        "metadata_included": False,
        "metadata_bytes": row["receipt_bytes"],
        "metadata_reason": "page_metadata_byte_budget_exhausted",
    }


def page_receipt(
    records: list[dict],
    total: int,
    offset: int,
    limit: int,
    metadata_read_bytes: int,
    verification_budget: int,
) -> dict:
    """Report whole-history omissions, page continuation and measured response bytes."""
    result = {
        "assets": records,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(records) < total,
        "verification_byte_budget": verification_budget,
        "metadata_read_byte_budget": MAX_PAGE_METADATA_BYTES,
        "metadata_read_bytes": metadata_read_bytes,
        "metadata_omitted_rows": sum(not r["metadata_included"] for r in records),
        "serialized_output_byte_budget": MAX_PAGE_OUTPUT_BYTES,
        "serialized_output_bytes": 0,
    }
    for _ in range(3):
        result["serialized_output_bytes"] = serialized_bytes(result)
    return result


def encode_receipts(receipts: list[dict]) -> str:
    """Encode the entire history, rejecting capacity without discarding aliases."""
    if not receipts or len(receipts) > 128:
        raise ValueError("Asset source receipt limit reached; no aliases were discarded")
    encoded = json.dumps(receipts, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode()) > MAX_ASSET_RECEIPTS_BYTES:
        raise ValueError(
            "Asset serialized receipt aggregate limit reached; no history was discarded"
        )
    return encoded


def _invalid_constant(value: str):
    """Reject non-JSON numeric constants in corrupted catalog metadata."""
    raise ValueError("Asset receipt contains a non-JSON numeric constant")


def decode_receipts(value: str | None) -> list[dict]:
    """Parse only bounded histories and validate fields consumed by the catalog."""
    if not isinstance(value, str) or len(value.encode()) > MAX_ASSET_RECEIPTS_BYTES:
        raise ValueError("Asset serialized receipts exceed the byte limit or are invalid")
    try:
        receipts = json.loads(value, parse_constant=_invalid_constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError("Asset receipt metadata is invalid JSON") from exc
    if not isinstance(receipts, list) or not receipts or len(receipts) > 128:
        raise ValueError("Asset receipt history is invalid")
    for receipt in receipts:
        if (
            not isinstance(receipt, dict)
            or not valid_digest(receipt.get("alias_sha256"))
            or not isinstance(receipt.get("source"), str)
            or not isinstance(receipt.get("acquisition"), dict)
        ):
            raise ValueError("Asset receipt metadata is invalid")
    encode_receipts(receipts)
    return receipts


def _redact(value):
    """Apply the shared redactor to retained structured acquisition provenance."""
    if isinstance(value, str):
        return redaction.redact_text(value)
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    return value


def make_receipt(alias: str, provenance: dict) -> dict:
    """Bound incoming metadata and the final redacted representation separately."""
    receipt = {
        "alias_sha256": hashlib.sha256(alias.encode()).hexdigest(),
        "source": redaction.redact_text(alias),
        "acquisition": provenance,
    }
    encode_receipts([receipt])
    receipt["acquisition"] = _redact(provenance)
    encode_receipts([receipt])
    return receipt
