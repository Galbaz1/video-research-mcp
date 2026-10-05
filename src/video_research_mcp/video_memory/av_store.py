"""Append-only AV-memory revisions, retained artifacts, vectors, facts and identities.

Vector codec adapted from QwenLM/Qwen-MM-Plugins@07736672525443c7f8a3f6405eed37d2236f023f
``src/capabilities/omni-memory/qwen_mm_plugins_omni_memory/omni_core.py``
(``emb_encode``/``emb_decode``), Apache-2.0. Changed: little-endian float64 so endpoint
floats round-trip bit-exactly, no NumPy, nonfinite or zero vectors rejected.
Fact merge adapted from ``skill/script/build_memory/stages.py`` (``merge_triple``,
``_resolve``), Apache-2.0. Changed: stable content IDs, every losing value stays as a
superseded fact, and facts may cite only stored records.
"""

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
from uuid import uuid4

from ..local_path_policy import enforce_local_access_root, resolve_path
from ..media_local_io import _open_regular
from ..models.video_memory_av import AlignRequest, Fact, IdentityRevision, MemoryState

MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
_REVISION = re.compile(r"^rev-(\d{6})\.json$")
_RANK = {"high": 3, "medium": 2, "low": 1}


def local_path(value: str) -> Path:
    """Resolve a caller path under the configured local access root."""
    return enforce_local_access_root(resolve_path(value))


def canonical(value) -> bytes:
    """Finite sorted compact UTF-8 JSON used for hashing and storage."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish(path: Path, data: bytes) -> bool:
    """Create *path* with complete *data* only if absent; never overwrite in place."""
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.pending")
    with temporary.open("xb") as stream:
        temporary.chmod(0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    except FileExistsError:
        return False
    finally:
        temporary.unlink(missing_ok=True)
    _fsync_directory(path.parent)
    return True


def load(root: Path, expected_source_sha256: str) -> MemoryState | None:
    """Return the newest validated revision bound to the expected source, if any."""
    if not root.is_dir():
        return None
    numbers = sorted(int(m.group(1)) for p in root.iterdir() if (m := _REVISION.match(p.name)))
    if not numbers:
        return None
    path = root / f"rev-{numbers[-1]:06d}.json"
    try:
        with _open_regular(path) as reader:
            data = reader.read(MAX_SNAPSHOT_BYTES + 1)
    except PermissionError as exc:
        raise ValueError("Memory revision is a symlink or not a regular file") from exc
    if len(data) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Memory revision exceeds 64 MiB")
    state = MemoryState.model_validate_json(data)
    if state.revision != numbers[-1]:
        raise ValueError("Memory revision filename and content disagree")
    if state.source.sha256 != expected_source_sha256:
        raise ValueError("Memory source SHA-256 differs from expected_source_sha256")
    return state


def commit(root: Path, state: MemoryState, retained: dict[str, bytes]) -> dict:
    """Serialize and bound the whole revision before any write, then publish it once."""
    data = canonical(MemoryState.model_validate(state.model_dump()).model_dump(mode="json"))
    if len(data) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Memory snapshot exceeds 64 MiB; nothing was written")
    root.mkdir(mode=0o700, exist_ok=True)
    (root / "artifacts").mkdir(mode=0o700, exist_ok=True)
    for digest, payload in sorted(retained.items()):
        target = root / "artifacts" / f"{digest}.json"
        if not publish(target, payload) and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("Retained artifact address holds different bytes")
    name = f"rev-{state.revision:06d}.json"
    if not publish(root / name, data):
        raise ValueError("Memory revision conflict: another writer committed this revision")
    return {"revision": state.revision, "path": name, "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data)}


def encode_vector(values: list[float]) -> str:
    """Encode endpoint floats as ``f64:<base64 little-endian IEEE-754>``."""
    if not values or not all(math.isfinite(v) for v in values) or not any(values):
        raise ValueError("Embedding vectors must be nonempty, finite and nonzero")
    return "f64:" + base64.b64encode(struct.pack(f"<{len(values)}d", *values)).decode("ascii")


def decode_vector(text: str) -> list[float]:
    """Decode a tagged float64 vector; any other encoding is an error."""
    if not text.startswith("f64:"):
        raise ValueError("Unrecognised embedding encoding")
    raw = base64.b64decode(text[4:], validate=True)
    if not raw or len(raw) % 8:
        raise ValueError("Embedding bytes are not whole float64 values")
    return list(struct.unpack(f"<{len(raw) // 8}d", raw))


def fact_id(subject_id: str, key: str, value: str) -> str:
    """Stable ID for one subject/key/normalized value claim."""
    norm = " ".join(value.lower().split())
    return "F:" + hashlib.sha256(f"{subject_id}\x1f{key}\x1f{norm}".encode()).hexdigest()[:12]


def _absorb(target: Fact, incoming: Fact, revision: int) -> None:
    target.evidence_ids = sorted(set(target.evidence_ids) | set(incoming.evidence_ids))[:64]
    if _RANK[incoming.confidence] > _RANK[target.confidence]:
        target.confidence = incoming.confidence
    target.updated_revision = revision


def merge_fact(facts: list[Fact], incoming: Fact, revision: int) -> str:
    """Merge by key: same value updates, a different value supersedes the loser."""
    by_id = {f.fact_id: f for f in facts}
    active = next((f for f in facts if f.status == "active" and f.subject_id == incoming.subject_id
                   and f.key == incoming.key), None)
    if active is not None and active.fact_id == incoming.fact_id:
        _absorb(active, incoming, revision)
        return "update"
    known = by_id.get(incoming.fact_id)
    if known is None:
        facts.append(incoming)
        known = incoming
    else:
        _absorb(known, incoming, revision)
    if active is None:
        known.status, known.superseded_by = "active", None
        return "create"
    current = (_RANK[active.confidence], len(active.evidence_ids), 0)
    if (_RANK[known.confidence], len(known.evidence_ids), 1) >= current:
        winner, loser = known, active
    else:
        winner, loser = active, known
    winner.status, winner.superseded_by = "active", None
    loser.status, loser.superseded_by, loser.updated_revision = "superseded", winner.fact_id, revision
    return "conflict"


def _evidence_names_person(state: MemoryState, request: AlignRequest) -> tuple[bool, bool]:
    records = {r.record_id: r for r in state.records}
    suggestions = {s.suggestion_id: s for s in state.suggestions}
    unknown = set(request.evidence_ids) - records.keys() - suggestions.keys()
    if unknown:
        raise ValueError(f"Alignment evidence is not stored: {sorted(unknown)}")
    cited_records = [records[e] for e in request.evidence_ids if e in records]
    cited_suggestions = [suggestions[e] for e in request.evidence_ids if e in suggestions]
    linked = any(r.person_id == request.person_id for r in cited_records) or any(
        s.person_id == request.person_id for s in cited_suggestions)
    name = (request.name or "").lower()
    named = bool(name) and (any(name in r.text.lower() for r in cited_records) or any(
        s.name.lower() == name and s.person_id == request.person_id for s in cited_suggestions))
    return linked, named


def align(state: MemoryState, request: AlignRequest, revision: int) -> IdentityRevision:
    """Append one identity revision after checking stored, person-linked evidence."""
    person = next((p for p in state.persons if p.person_id == request.person_id), None)
    if person is None:
        raise ValueError(f"Unknown person_id {request.person_id}")
    linked, named = _evidence_names_person(state, request)
    if not linked:
        raise ValueError("Alignment evidence must cite this person's records or suggestions")
    if request.basis == "evidence_aligned" and request.name is not None and not named:
        raise ValueError("Evidence-aligned names must occur in the cited evidence")
    count = sum(1 for r in state.identity_revisions if r.person_id == person.person_id)
    entry = IdentityRevision(
        revision_id=f"{person.person_id}@r{count + 1}", person_id=person.person_id,
        name=request.name, previous_name=person.name, basis=request.basis,
        evidence_ids=sorted(set(request.evidence_ids)), store_revision=revision, note=request.note)
    state.identity_revisions.append(entry)
    person.name = request.name
    person.identity_status = "unknown" if request.name is None else request.basis
    return entry
