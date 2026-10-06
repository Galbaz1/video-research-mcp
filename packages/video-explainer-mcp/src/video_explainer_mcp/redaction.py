"""Remove credentials from diagnostic text without hiding the failing resource."""

from __future__ import annotations

import os
import re
from urllib.parse import quote, quote_plus, urlsplit, urlunsplit

_SECRET_NAME = r"(?<![\w-])(?:[\w-]*(?:api[_-]?key|token|secret|password)|cookie|authorization)"
_QUOTED_SECRET = re.compile(rf"(['\"]?{_SECRET_NAME}['\"]?\s*[:=]\s*)(['\"])(.*?)\2", re.I)
_PLAIN_SECRET = re.compile(rf"({_SECRET_NAME}\s*[:=]\s*)[^\s,;\}}]+", re.I)
_HEADERS = re.compile(r"(\b(?:authorization|cookie|set-cookie)\s*[:=]\s*)[^\r\n]+", re.I)
_URL = re.compile(r"\b[a-z][a-z0-9+.-]{0,63}://[^\s\"'<>]+", re.I)


def _redact_url(match: re.Match) -> str:
    """Keep the endpoint and path while removing URL credentials and parameters."""
    value = match.group().rstrip(".,;)")
    suffix = match.group()[len(value) :]
    try:
        parts = urlsplit(value)
        return (
            urlunsplit(
                (
                    parts.scheme,
                    parts.netloc.rsplit("@", 1)[-1],
                    parts.path,
                    "[redacted]" if parts.query else "",
                    "[redacted]" if parts.fragment else "",
                )
            )
            + suffix
        )
    except ValueError:
        return "[redacted-url]" + suffix


def redact_text(value: str) -> str:
    """Redact known environment secrets, credential fields, headers and signed URLs."""
    for name, secret in os.environ.items():
        if len(secret) >= 4 and re.search(r"(?:API_KEY|TOKEN|SECRET|PASSWORD|COOKIE)$", name, re.I):
            for encoded in {secret, quote(secret, safe=""), quote_plus(secret)}:
                value = value.replace(encoded, "[redacted]")
    value = _URL.sub(_redact_url, value)
    value = _QUOTED_SECRET.sub(lambda m: f"{m[1]}{m[2]}[redacted]{m[2]}", value)
    value = _HEADERS.sub(r"\1[redacted]", value)
    return _PLAIN_SECRET.sub(r"\1[redacted]", value)
