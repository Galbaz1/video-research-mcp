"""Model-separated local voiceprint registry with strict validation and locked 0600 atomic writes.

Identity is (speaker name, full embedding-model SHA-256); the declared dimension
must agree per model. Only ``enroll`` writes. Matching ranks suggestions from
same-model entries and never assigns them.
"""

import fcntl
import hashlib
import json
import math
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .transcript_captions import strict_json

FORMAT = "speaker-registry/v1"
MAX_REGISTRY_BYTES = 16 * 1024 * 1024
_ENTRY_KEYS = frozenset({"name", "model", "embedding", "added", "provenance", "consent"})
_MODEL_KEYS = frozenset({"basename", "sha256", "dimension"})
_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
_ROLE = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_DIGEST = re.compile(r"[a-f0-9]{64}")


def _matches(pattern: re.Pattern, value) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def unit(vector: list) -> list[float]:
    """Return the unit vector, refusing zero or non-finite norms."""
    norm = math.sqrt(math.fsum(value * value for value in vector))
    if not norm or not math.isfinite(norm):
        raise ValueError("Voiceprints must be finite non-zero vectors")
    return [value / norm for value in vector]


def cosine(left: list, right: list) -> float:
    """Pure-Python cosine similarity of two equal-length vectors."""
    return math.fsum(a * b for a, b in zip(unit(left), unit(right), strict=True))


def check_vector(vector, dimension: int) -> list:
    """Admit only a finite, non-zero numeric vector of exactly the model dimension."""
    if (not isinstance(vector, list) or len(vector) != dimension
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in vector)):
        raise ValueError(f"Voiceprint must be {dimension} finite numbers")
    unit(vector)
    return vector


def _check_entry(entry) -> tuple[str, str, int]:
    if not isinstance(entry, dict) or not _ENTRY_KEYS <= set(entry) <= _ENTRY_KEYS | {"role"}:
        raise ValueError("Speaker registry entry keys are not exact")
    model = entry["model"]
    if (not isinstance(model, dict) or set(model) != _MODEL_KEYS or not _matches(_DIGEST, model["sha256"])
            or not isinstance(model["basename"], str) or type(model["dimension"]) is not int
            or not 1 <= model["dimension"] <= 4096):
        raise ValueError("Speaker registry model key requires basename, full SHA-256 and dimension")
    if not _matches(_NAME, entry["name"]) or ("role" in entry and not _matches(_ROLE, entry["role"])):
        raise ValueError("Speaker registry name or role is invalid")
    consent = entry["consent"]
    if (not isinstance(consent, dict) or set(consent) != {"asserted_by_caller", "recorded_at"}
            or consent["asserted_by_caller"] is not True or not isinstance(entry["added"], str)
            or not isinstance(entry["provenance"], dict)):
        raise ValueError("Speaker registry entry lacks caller-asserted consent, timestamp or provenance")
    check_vector(entry["embedding"], model["dimension"])
    return entry["name"], model["sha256"], model["dimension"]


def validate(value) -> dict:
    """Require exact keys, unique (name, model SHA) identities and one dimension per model."""
    if not isinstance(value, dict) or set(value) != {"format", "speakers"} or value["format"] != FORMAT:
        raise ValueError(f"Speaker registry must be a {FORMAT} object")
    if not isinstance(value["speakers"], list):
        raise ValueError("Speaker registry speakers must be a list")
    identities, dimensions = set(), {}
    for entry in value["speakers"]:
        name, model, dimension = _check_entry(entry)
        if (name, model) in identities:
            raise ValueError(f"Speaker registry has duplicate speaker '{name}' for model {model}")
        identities.add((name, model))
        if dimensions.setdefault(model, dimension) != dimension:
            raise ValueError(f"Speaker registry has inconsistent dimensions for model {model}")
    return value


def read(path: Path) -> tuple[dict, str | None]:
    """Return the validated registry and its SHA-256; an absent file is an empty registry."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {"format": FORMAT, "speakers": []}, None
    with os.fdopen(fd, "rb") as stream:
        mode = os.fstat(stream.fileno()).st_mode
        if not stat.S_ISREG(mode) or mode & 0o077:
            raise PermissionError("Speaker registry must be a regular file with mode 0600")
        data = stream.read(MAX_REGISTRY_BYTES + 1)
    if len(data) > MAX_REGISTRY_BYTES:
        raise ValueError("Speaker registry exceeds 16 MiB")
    return validate(strict_json(data)), hashlib.sha256(data).hexdigest()


@contextmanager
def _locked(path: Path):
    """Serialize writers through an advisory 0600 sidecar lock; readers rely on atomic replace."""
    fd = os.open(path.with_name(path.name + ".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _write(path: Path, registry: dict, existed: bool) -> str:
    """Write 0600 bytes, fsync, then replace or create-if-absent via link; never partial."""
    data = (json.dumps(validate(registry), sort_keys=True, indent=1, allow_nan=False) + "\n").encode()
    if len(data) > MAX_REGISTRY_BYTES:
        raise ValueError("Speaker registry exceeds 16 MiB")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".pending", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if existed:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return hashlib.sha256(data).hexdigest()


def enroll(path: Path, entry: dict, replace_existing: bool) -> dict:
    """Write exactly one (name, model) entry under the lock; other entries stay unchanged."""
    _check_entry(entry)
    with _locked(path):
        registry, before = read(path)
        key = (entry["name"], entry["model"]["sha256"])
        current = [e for e in registry["speakers"] if (e["name"], e["model"]["sha256"]) == key]
        if current and not replace_existing:
            raise FileExistsError(f"Speaker '{key[0]}' already has a voiceprint for this model; set replace_existing")
        previous = cosine(current[0]["embedding"], entry["embedding"]) if current else None
        registry["speakers"] = [e for e in registry["speakers"] if (e["name"], e["model"]["sha256"]) != key]
        registry["speakers"].append(entry)
        after = _write(path, registry, before is not None)
    return {"registry_sha256_before": before, "registry_sha256_after": after,
            "replaced": bool(current), "previous_voiceprint_cosine": previous}


def public_entry(entry: dict) -> dict:
    """Entry metadata without its voiceprint."""
    return {key: value for key, value in entry.items() if key != "embedding"}


def listing(registry: dict) -> dict:
    """Group entries by embedding model; voiceprints are never returned."""
    models: dict[str, dict] = {}
    for entry in registry["speakers"]:
        group = models.setdefault(entry["model"]["sha256"], {"model": entry["model"], "speakers": []})
        group["speakers"].append({k: v for k, v in public_entry(entry).items() if k != "model"})
    groups = sorted(models.values(), key=lambda group: group["model"]["sha256"])
    for group in groups:
        group["speakers"].sort(key=lambda speaker: speaker["name"])
    return {"format": FORMAT, "speaker_count": len(registry["speakers"]), "models": groups}


def rank(registry: dict, model: dict, centroids: dict, expected: list, top: int = 3) -> tuple[dict, int]:
    """Rank same-model voiceprints per cluster as unapplied suggestions; count ignored entries."""
    same = [e for e in registry["speakers"] if e["model"]["sha256"] == model["sha256"]]
    ignored = len(registry["speakers"]) - len(same)
    if any(e["model"]["dimension"] != model["dimension"] for e in same):
        raise ValueError("Registry dimension differs from the runtime embedding model")
    if expected:
        missing = sorted(set(expected) - {e["name"] for e in same})
        if missing:
            raise ValueError(f"Expected speakers lack a voiceprint for this embedding model: {', '.join(missing)}")
        same = [e for e in same if e["name"] in expected]
    suggestions = {}
    for cluster, centroid in sorted(centroids.items()):
        scored = [{"name": e["name"], "cosine": cosine(centroid, e["embedding"]), "applied": False} for e in same]
        suggestions[cluster] = sorted(scored, key=lambda s: (-s["cosine"], s["name"]))[:top]
    return suggestions, ignored
