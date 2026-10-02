"""Host-owned bounded approval files and exact simulator-command commitments."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from .media_local_io import _open_regular


def canonical(value) -> bytes:
    """Serialize finite operation evidence deterministically."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def digest(value) -> str:
    """Commit the exact finite JSON proposal or state."""
    return hashlib.sha256(canonical(value)).hexdigest()


def _unique_object(pairs):
    """Reject duplicate authority fields instead of accepting a last-write override."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate host authority field")
        result[key] = value
    return result


def host_approval(path: Path | None, commitment: str) -> dict:
    """Read an external private owner file; never modify or infer human approval."""
    if path is None:
        return {"authorized": False, "reason": "host_authority_not_configured"}
    try:
        with _open_regular(path) as reader:
            before = os.fstat(reader.fileno())
            if before.st_uid != os.geteuid() or before.st_mode & 0o077:
                raise ValueError("Host authority must be private to the current owner")
            if before.st_size > 16 * 1024:
                raise ValueError("Host authority exceeds 16 KiB")
            data = reader.read(16 * 1024 + 1)
            after = os.fstat(reader.fileno())
        current = path.lstat()
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_uid", "st_mode")
        if len(data) > 16 * 1024 or any(getattr(before, k) != getattr(v, k)
                                      for k in fields for v in (after, current)):
            raise ValueError("Host authority changed during reading")
        value = json.loads(data, object_pairs_hook=_unique_object)
        approvals = value.get("approved_commands") if type(value) is dict else None
        if (type(value) is not dict or set(value) != {"approved_commands"}
                or type(approvals) is not list or len(approvals) > 64
                or any(type(item) is not str or not re.fullmatch(r"[0-9a-f]{64}", item) for item in approvals)
                or len(set(approvals)) != len(approvals)):
            raise ValueError("Invalid bounded host authority schema")
        return {"authorized": commitment in approvals,
                "reason": "host_approved" if commitment in approvals else "commitment_not_approved",
                "authority_sha256": hashlib.sha256(data).hexdigest()}
    except (OSError, ValueError, UnicodeError):
        return {"authorized": False, "reason": "host_authority_unavailable_or_invalid"}
