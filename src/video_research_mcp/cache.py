"""Deterministic result contracts bound to freshly checked original source bytes."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .config import get_config
from .media_identity import SourceIdentity, identify_source, valid_digest
from .redaction import redact_text

logger = logging.getLogger(__name__)
_CONTRACT_FIELDS = {
    "source_digest",
    "source_revision",
    "provider",
    "account_scope",
    "model",
    "tool_name",
    "output_schema",
    "thinking_level",
    "prompt",
    "metadata",
    "preprocessing",
    "window",
    "sampling",
    "retrieval_revision",
}
_REGISTRY_FILES = {"media_identity_registry.json", "context_cache_registry.json"}


def _cache_dir() -> Path:
    """Return the existing configured cache directory, creating it for result I/O."""
    directory = Path(get_config().cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def normalized_contract(contract: dict) -> dict:
    """Canonicalize JSON mapping order without changing prompt or schema meaning."""
    if not isinstance(contract, dict) or not _CONTRACT_FIELDS <= contract.keys():
        raise ValueError("Complete result cache contract required")
    return json.loads(json.dumps(contract, sort_keys=True, separators=(",", ":"), allow_nan=False))


def cache_key(
    content_id: str,
    tool_name: str,
    model: str,
    instruction: str = "",
    *,
    contract: dict | None = None,
) -> str:
    """Hash the complete contract; caller labels never become filesystem components."""
    descriptor = (
        normalized_contract(contract)
        if contract is not None
        else {
            "legacy_unusable": True,
            "content_id": content_id,
            "tool": tool_name,
            "model": model,
            "instruction": instruction,
        }
    )
    encoded = json.dumps(descriptor, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "v2_" + hashlib.sha256(encoded.encode()).hexdigest()


def cache_path(
    content_id: str,
    tool_name: str,
    model: str,
    instruction: str = "",
    *,
    contract: dict | None = None,
) -> Path:
    """Return a filename containing only the version and full contract hash."""
    return _cache_dir() / (
        cache_key(content_id, tool_name, model, instruction, contract=contract) + ".json"
    )


def _current_binding(
    contract: dict | None, source: SourceIdentity | None, tool: str, model: str
) -> bool:
    """Require a complete contract and recheck original bytes before any replay/write."""
    if source is None or source.state != "fresh" or not valid_digest(source.digest):
        return False
    try:
        normalized = normalized_contract(contract)
    except (ValueError, TypeError):
        return False
    if (
        normalized["source_digest"] != source.digest
        or normalized["source_revision"] != source.revision
    ):
        return False
    if normalized["tool_name"] != tool or normalized["model"] != model:
        return False
    current = identify_source(source.alias, expected_digest=source.digest, persist=False)
    if current.state != "fresh":
        invalidate_source(source.digest)
        return False
    return True


def _valid_analysis(analysis) -> bool:
    """Reject errors and artifact proof paths lacking a trusted validation receipt."""
    return (
        isinstance(analysis, dict)
        and bool(analysis)
        and not {"error", "artifacts"} & analysis.keys()
    )


def load(
    content_id: str,
    tool_name: str,
    model: str,
    instruction: str = "",
    *,
    contract: dict | None = None,
    source: SourceIdentity | None = None,
) -> dict | None:
    """Return an exact fresh contract match; incomplete and legacy entries miss."""
    if not _current_binding(contract, source, tool_name, model):
        return None
    path = cache_path(content_id, tool_name, model, instruction, contract=contract)
    try:
        if not path.is_file():
            return None
        modified = datetime.fromtimestamp(path.stat().st_mtime)
        if datetime.now() > modified + timedelta(days=get_config().cache_ttl_days):
            return None
        envelope = json.loads(path.read_text())
        if not isinstance(envelope, dict) or envelope.get("cache_version") != 2:
            return None
        if envelope.get("contract") != normalized_contract(contract):
            return None
        analysis = envelope.get("analysis")
        return analysis if _valid_analysis(analysis) else None
    except (ValueError, OSError) as error:
        logger.warning("Cache read error: %s", redact_text(str(error)))
        return None


def save(
    content_id: str,
    tool_name: str,
    model: str,
    analysis: dict,
    instruction: str = "",
    *,
    contract: dict | None = None,
    source: SourceIdentity | None = None,
) -> bool:
    """Atomically retain only a complete contract with freshly checked original bytes."""
    if not _valid_analysis(analysis) or not _current_binding(contract, source, tool_name, model):
        return False
    path = cache_path(content_id, tool_name, model, instruction, contract=contract)
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    try:
        envelope = {
            "cache_version": 2,
            "cached_at": datetime.now().isoformat(),
            "content_id": content_id,
            "tool": tool_name,
            "model": model,
            "contract": normalized_contract(contract),
            "analysis": analysis,
        }
        temporary.write_text(json.dumps(envelope, indent=2))
        temporary.replace(path)
        return True
    except (OSError, ValueError) as error:
        logger.warning("Cache write error: %s", redact_text(str(error)))
        return False
    finally:
        temporary.unlink(missing_ok=True)


def _entry_files() -> list[Path]:
    """Separate result entries from source/context registry sidecars."""
    return [path for path in _cache_dir().glob("*.json") if path.name not in _REGISTRY_FILES]


def clear(content_id: str | None = None) -> int:
    """Remove exact source dependencies, including all their request variants."""
    removed = 0
    for path in _entry_files():
        try:
            if content_id is not None:
                envelope = json.loads(path.read_text())
                if not isinstance(envelope, dict):
                    continue
                matches = envelope.get("content_id") == content_id
                contract = envelope.get("contract", {})
                matches = (
                    matches
                    or isinstance(contract, dict)
                    and contract.get("source_digest") == content_id
                )
                if not matches:
                    continue
            path.unlink()
            removed += 1
        except (ValueError, OSError):
            continue
    return removed


def invalidate_source(digest: str) -> int:
    """Invalidate result and local context dependencies without provider operations."""
    removed = clear(digest)
    from .context_cache import invalidate_content

    invalidate_content(digest)
    return removed


def stats() -> dict:
    """Report result-entry storage, including retained legacy files."""
    files = _entry_files()
    return {
        "cache_dir": str(_cache_dir()),
        "total_files": len(files),
        "total_size_mb": round(sum(path.stat().st_size for path in files) / 1024**2, 2),
        "ttl_days": get_config().cache_ttl_days,
    }


def list_entries() -> list[dict]:
    """Audit entries without interpreting uninspected sources as fresh."""
    entries = []
    for path in _entry_files():
        try:
            envelope = json.loads(path.read_text())
            if isinstance(envelope, dict):
                entries.append(
                    {
                        "file": path.name,
                        "content_id": envelope.get("content_id"),
                        "tool": envelope.get("tool"),
                        "cached_at": envelope.get("cached_at"),
                        "cache_state": "contract_entry"
                        if envelope.get("cache_version") == 2
                        else "legacy_miss",
                        "source_state": "not_checked",
                    }
                )
        except (ValueError, OSError):
            continue
    return sorted(entries, key=lambda entry: entry.get("cached_at") or "", reverse=True)
