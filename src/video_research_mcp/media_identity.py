"""Original local byte identity and aliases; remote freshness stays unknown."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlparse
from uuid import uuid4

from .config import get_config
from .local_path_policy import enforce_local_access_root, resolve_path
from .media_local_io import _open_regular


@dataclass(frozen=True)
class SourceIdentity:
    """Current byte observation, separate from semantic or artifact verification."""

    alias: str
    digest: str | None = None
    revision: str | None = None
    state: str = "unknown"
    aliases: tuple[str, ...] = ()
    previous_digest: str | None = None


def valid_digest(value: str | None) -> bool:
    """Recognize complete byte commitments, excluding old truncated identifiers."""
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _registry_path() -> Path:
    """Resolve the existing cache's identity sidecar without creating directories."""
    return Path(get_config().cache_dir) / "media_identity_registry.json"


def _read_aliases() -> dict:
    """Read only validated alias records; corruption never supplies freshness."""
    try:
        data = json.loads(_registry_path().read_text())
        if not isinstance(data, dict) or data.get("version") != 1:
            return {}
        aliases = data.get("aliases", {})
        return {
            alias: record
            for alias, record in aliases.items()
            if isinstance(alias, str)
            and isinstance(record, dict)
            and valid_digest(record.get("digest"))
        }
    except (OSError, ValueError, AttributeError):
        return {}


def _write_aliases(aliases: dict) -> None:
    """Atomically retain identity metadata; failed writes leave prior state intact."""
    target = _registry_path()
    temporary = target.with_suffix(f".{uuid4().hex}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps({"version": 1, "aliases": aliases}, sort_keys=True))
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _hash_original(path: Path) -> str:
    """Hash bounded original bytes through an admitted, stable regular descriptor."""
    cfg = get_config()
    ceiling = cfg.media_max_input_bytes
    deadline = time.monotonic() + cfg.media_acquire_timeout_seconds
    digest, size = hashlib.sha256(), 0
    with _open_regular(path) as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > ceiling:
            raise ValueError("Source exceeds MEDIA_MAX_INPUT_BYTES")
        while size < ceiling:
            chunk = stream.read(min(64 * 1024, ceiling - size))
            if not chunk:
                break
            if time.monotonic() > deadline:
                raise TimeoutError("Source exceeds MEDIA_ACQUIRE_TIMEOUT_SECONDS")
            size += len(chunk)
            digest.update(chunk)
        after = os.fstat(stream.fileno())
        current = path.lstat()
        if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
            raise ValueError("Source path changed while reading")
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns
        ) or size != before.st_size:
            raise ValueError("Source changed while reading")
    return digest.hexdigest()


def _persist_observation(identity: SourceIdentity, records: dict) -> SourceIdentity:
    """Maintain aliases and invalidate old dependent results on mutation/deletion."""
    if identity.digest:
        records[identity.alias] = {"digest": identity.digest, "state": identity.state}
    elif identity.alias in records:
        records[identity.alias]["state"] = identity.state
    try:
        _write_aliases(records)
    except OSError:
        pass
    if identity.previous_digest and (
        identity.previous_digest != identity.digest or identity.state != "fresh"
    ):
        from .cache import invalidate_source

        invalidate_source(identity.previous_digest)
    return identity


def identify_source(
    source: str, expected_digest: str | None = None, *, persist: bool = True
) -> SourceIdentity:
    """Inspect original bytes; aliases and invalidation require explicit persistence."""
    if urlparse(source).scheme:
        return SourceIdentity(alias=source)
    try:
        path = enforce_local_access_root(resolve_path(source))
    except (OSError, ValueError, PermissionError):
        return SourceIdentity(alias=source)
    records = _read_aliases() if persist else {}
    alias = str(path)
    previous = records.get(alias, {}).get("digest")
    try:
        digest = _hash_original(path)
        state = "fresh"
        if expected_digest is not None:
            state = (
                "unknown"
                if not valid_digest(expected_digest)
                else ("fresh" if expected_digest == digest else "stale")
            )
        prior = previous or (
            expected_digest if valid_digest(expected_digest) and expected_digest != digest else None
        )
        aliases = tuple(
            sorted({alias, *(key for key, record in records.items() if record["digest"] == digest)})
        )
        identity = SourceIdentity(alias, digest, "sha256:" + digest, state, aliases, prior)
    except (OSError, ValueError):
        prior = previous or (expected_digest if valid_digest(expected_digest) else None)
        state = "deleted" if not path.exists() and prior else "unknown"
        identity = SourceIdentity(alias=alias, state=state, previous_digest=prior)
    return _persist_observation(identity, records) if persist else identity
