"""Project material receipts, rights checks and bounded durable manifests."""

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path

from .evidence import atomic_write, validate_evidence_packet
from .file_io import open_regular
from .models.materials import MaterialRights, PinnedFile, StockConfig
from .planning_sources import canonical
from .render_storyboard_sources import confined_path, file_pin, project_object

MAX_ASSET_BYTES = 64 * 1024 * 1024
MANIFEST = "materials-manifest.json"


def pinned_object(project: Path, ref: PinnedFile) -> dict:
    """Read existing bounded duplicate-safe project JSON at its expected digest."""
    value, pin = project_object(project, ref.path)
    if pin["sha256"] != ref.sha256:
        raise ValueError("Pinned project JSON changed")
    return value


def rights_receipt(project: Path, ref: PinnedFile, sha: str, principal: str) -> dict:
    """Refuse missing, stale, changed, foreign-principal or nonpermissive rights."""
    rights = MaterialRights.model_validate(pinned_object(project, ref))
    now = datetime.now(timezone.utc)
    if (rights.source_sha256 != sha or rights.principal != principal
            or not rights.clip_use_allowed or not rights.retrieved_at <= now < rights.valid_until):
        raise ValueError("Material rights are absent, stale or do not authorize these bytes/caller")
    return {**rights.model_dump(mode="json"), "receipt_sha256": ref.sha256,
            "authority_basis": "caller_declared_unverified", "rights_verified": False}


def source_receipt(project: Path, clip, principal: str) -> dict:
    """Bind local bytes, explicit provenance and optional original evidence lineage."""
    source = confined_path(project, clip.source.path)
    pin = file_pin(source, MAX_ASSET_BYTES)
    if not pin["size_bytes"] or pin["sha256"] != clip.source.sha256:
        raise ValueError("Material source is empty or differs from its expected digest")
    rights = rights_receipt(project, clip.rights, pin["sha256"], principal)
    evidence = None
    for downloaded in load_manifest(project)["downloads"].values():
        if downloaded["path"] != clip.source.path:
            continue
        source_config = StockConfig.model_validate(pinned_object(project, PinnedFile.model_validate(downloaded["config"])))
        if (source_config.principal != principal or not source_config.download_allowed
                or source_config.valid_until.tzinfo is None
                or source_config.valid_until <= datetime.now(timezone.utc)):
            raise ValueError("Downloaded material source permission is stale or absent")
        if clip.use != "illustrative":
            raise ValueError("Stock materials remain illustrative")
    if clip.use == "evidentiary":
        if not clip.evidence_packet or not clip.evidence_source_id:
            raise ValueError("Evidentiary material requires an existing original evidence binding")
        packet = pinned_object(project, clip.evidence_packet)
        report = validate_evidence_packet(packet, project)
        sources = packet.get("sources", [])
        linked = [s for s in sources if s["id"] == clip.evidence_source_id]
        if (report["source_errors"] or len(linked) != 1 or linked[0]["sha256"] != pin["sha256"]
                or linked[0]["path"] != clip.source.path or linked[0]["asset_kind"] != "original"):
            raise ValueError("Evidentiary material does not bind these exact original source bytes")
        source = linked[0]
        if source["modality"] != clip.kind:
            raise ValueError("Evidentiary source modality differs from the material kind")
        start, end = clip.start_seconds * 1000, (clip.start_seconds + clip.duration_seconds) * 1000
        if clip.kind == "video" and not any(s["start_ms"] <= start < end <= s["end_ms"]
                                             for s in source["observed_intervals"]):
            raise ValueError("Evidentiary clip extends outside actually observed original intervals")
        evidence = {"packet_sha256": clip.evidence_packet.sha256, "source_id": source["id"],
                    "source_revision": source["revision"], "source_sha256": source["sha256"],
                    "original_start_ms": start, "original_end_ms": end, "basis": "retained_observation_record"}
    return {"path": clip.source.path, **pin, "rights": rights, "use": clip.use,
            "evidence_source_id": clip.evidence_source_id, "evidence": evidence, "semantic_support": "not_verified"}


def load_manifest(project: Path) -> dict:
    """Read a bounded project manifest; reject altered shape rather than resetting it."""
    path = confined_path(project, MANIFEST)
    if not path.exists():
        return {"version": 1, "revision": 0, "outputs": {}, "downloads": {}}
    value, _ = project_object(project, MANIFEST)
    if (set(value) != {"version", "revision", "outputs", "downloads"}
            or value["version"] != 1 or not isinstance(value["revision"], int)
            or not isinstance(value["outputs"], dict) or not isinstance(value["downloads"], dict)
            or len(value["outputs"]) + len(value["downloads"]) > 64):
        raise ValueError("Materials manifest is invalid or exceeds64entries")
    return value


def save_manifest(project: Path, manifest: dict) -> None:
    """Atomically publish a finite manifest only after complete artifact qualification."""
    if len(manifest["outputs"]) + len(manifest["downloads"]) > 64:
        raise ValueError("Materials manifest exceeds64entries")
    manifest["revision"] += 1
    content = canonical(manifest)
    if len(content.encode()) > 1024 * 1024:
        raise ValueError("Materials manifest exceeds1MiB")
    atomic_write(confined_path(project, MANIFEST), content)


def snapshot(project: Path, ref: PinnedFile, target: Path) -> None:
    """Copy and hash exact stable input bytes into a private media work directory."""
    sha = hashlib.sha256()
    total = 0
    with open_regular(confined_path(project, ref.path)) as (source, info), target.open("xb") as out:
        if not 0 < info.st_size <= MAX_ASSET_BYTES:
            raise ValueError("Material input exceeds64MiB or is empty")
        while chunk := source.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_ASSET_BYTES:
                raise ValueError("Material input grew beyond64MiB")
            sha.update(chunk)
            out.write(chunk)
    if sha.hexdigest() != ref.sha256:
        raise ValueError("Material input changed before rendering")


def publish(project: Path, source: Path, name: str, expected_sha: str) -> Path:
    """Publish a new leaf through a verified directory FD without following symlinks."""
    target = confined_path(project, name)
    if target.parent != project:
        raise ValueError("Materials output must be a project root leaf")
    directory = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                             dir_fd=directory)
        created = os.fstat(descriptor)
        try:
            sha = hashlib.sha256()
            total = 0
            with os.fdopen(descriptor, "wb") as output, open_regular(source) as (stream, info):
                if not 0 < info.st_size <= MAX_ASSET_BYTES:
                    raise ValueError("Published material exceeds64MiB or is empty")
                while chunk := stream.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_ASSET_BYTES:
                        raise ValueError("Published material grew beyond64MiB")
                    sha.update(chunk)
                    output.write(chunk)
                if sha.hexdigest() != expected_sha:
                    raise ValueError("Qualified material changed before publication")
                output.flush()
                os.fsync(output.fileno())
            if os.stat(project).st_ino != os.fstat(directory).st_ino:
                raise ValueError("Project directory changed during output publication")
        except BaseException as error:
            try:
                current = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (created.st_dev, created.st_ino):
                    raise ValueError("Partial output identity changed; cleanup refused")
                os.unlink(name, dir_fd=directory)
            except (OSError, ValueError) as cleanup:
                error.add_note(f"Material partial output cleanup liability:{type(cleanup).__name__}")
            raise
    finally:
        os.close(directory)
    return target


def discard_published(project: Path, name: str, expected_sha: str, error: BaseException) -> None:
    """Preserve the primary publication error and refuse cleanup of changed/foreign bytes."""
    try:
        target = confined_path(project, name)
        if file_pin(target, MAX_ASSET_BYTES)["sha256"] != expected_sha:
            raise ValueError("Published output changed; cleanup refused")
        target.unlink()
    except (OSError, ValueError) as cleanup:
        error.add_note(f"Material publication cleanup liability:{type(cleanup).__name__}")
