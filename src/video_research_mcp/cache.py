"""Generic file-based analysis cache with TTL."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .config import get_config

logger = logging.getLogger(__name__)


def _cache_dir() -> Path:
    """Return the cache directory path, creating it if needed."""
    d = Path(get_config().cache_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_key(content_id: str, tool_name: str, model: str, instruction: str = "") -> str:
    """Generate ``{content_id}_{tool}_{instr_hash}_{model_hash}``.

    The *instruction* hash differentiates results for the same content
    analysed with different instructions (e.g. "summarize" vs "list recipes").
    """
    model_hash = hashlib.md5(model.encode()).hexdigest()[:8]
    instr_hash = hashlib.md5(instruction.encode()).hexdigest()[:8] if instruction else "default"
    return f"{content_id}_{tool_name}_{instr_hash}_{model_hash}"


def cache_path(
    content_id: str, tool_name: str, model: str, instruction: str = "",
) -> Path:
    """Return the full filesystem path for a cache entry's JSON file."""
    return _cache_dir() / f"{cache_key(content_id, tool_name, model, instruction)}.json"


def load(
    content_id: str, tool_name: str, model: str, instruction: str = "",
) -> dict | None:
    """Return cached result dict or *None* if miss/expired."""
    ttl = get_config().cache_ttl_days
    p = cache_path(content_id, tool_name, model, instruction)
    if not p.exists():
        return None
    mtime = datetime.fromtimestamp(p.stat().st_mtime)
    if datetime.now() > mtime + timedelta(days=ttl):
        logger.debug("Cache expired: %s", p.name)
        return None
    try:
        data = json.loads(p.read_text())
        logger.info("Cache hit: %s", p.name)
        return data.get("analysis") or data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Cache read error: %s", exc)
        return None


def save(
    content_id: str, tool_name: str, model: str, analysis: dict, instruction: str = "",
) -> bool:
    """Write *analysis* to cache. Returns True on success."""
    p = cache_path(content_id, tool_name, model, instruction)
    try:
        envelope = {
            "cached_at": datetime.now().isoformat(),
            "content_id": content_id,
            "tool": tool_name,
            "model": model,
            "analysis": analysis,
        }
        tmp = p.with_suffix(f".{uuid4().hex}.tmp")
        tmp.write_text(json.dumps(envelope, indent=2))
        tmp.replace(p)
        logger.info("Cached: %s", p.name)
        return True
    except OSError as exc:
        logger.warning("Cache write error: %s", exc)
        return False


def clear(content_id: str | None = None) -> int:
    """Remove cache files. If *content_id* given, only that ID."""
    removed = 0
    for f in _cache_dir().glob("*.json"):
        if content_id is None or f.name.startswith(f"{content_id}_"):
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def stats() -> dict:
    """Return cache statistics."""
    d = _cache_dir()
    files = list(d.glob("*.json"))
    total = sum(f.stat().st_size for f in files)
    return {
        "cache_dir": str(d),
        "total_files": len(files),
        "total_size_mb": round(total / (1024 * 1024), 2),
        "ttl_days": get_config().cache_ttl_days,
    }


def list_entries() -> list[dict]:
    """List all cached entries with metadata."""
    entries = []
    for f in _cache_dir().glob("*.json"):
        try:
            data = json.loads(f.read_text())
            entries.append(
                {
                    "file": f.name,
                    "content_id": data.get("content_id"),
                    "tool": data.get("tool"),
                    "cached_at": data.get("cached_at"),
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
    return sorted(entries, key=lambda x: x.get("cached_at") or "", reverse=True)
