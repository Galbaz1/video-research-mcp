"""Finite local collection, recall and owned-media lifecycle requests."""

from typing import Annotated, Literal

from pydantic import Field

from .corpus import ID, CorpusModel, Digest

LocalPath = Annotated[str, Field(min_length=1, max_length=2048)]


class Scope(CorpusModel):
    """Explicit workspace context within one canonical corpus index."""

    index_path: LocalPath
    workspace: ID


class Configure(Scope):
    """Enroll an empty private owned root and a finite media quota once."""

    action: Literal["configure"]
    owned_root: LocalPath
    quota_bytes: int = Field(ge=1, le=1024**3)


class Create(Scope):
    """Name or enroll an existing canonical collection without copying evidence."""

    action: Literal["create"]
    collection: ID
    expected_revision: int = Field(ge=0)
    kind: Literal["transcript", "comments", "media", "mixed"]
    label: str = Field(min_length=1, max_length=256)


class Select(Scope):
    """Persist a workspace's focus, or clear it without deleting data."""

    action: Literal["select"]
    collection: ID | None


class Read(Scope):
    """List metadata or recall existing evidence with finite pagination."""

    action: Literal["list", "recall", "health"]
    collection: ID | None = None
    offset: int = Field(default=0, ge=0, le=100000)
    limit: int = Field(default=20, ge=1, le=50)
    output_bytes: int = Field(default=32768, ge=1024, le=65536)


class Evidence(CorpusModel):
    """Existing artifact provenance; attached bytes remain externally owned."""

    asset_id: ID
    video_id: ID
    source_revision: ID
    media_digest: Digest
    kind: Literal["analysis", "transcript", "comments", "video", "audio", "thumbnail", "keyframe"]
    path: LocalPath
    sha256: Digest
    size_bytes: int = Field(ge=1, le=64 * 1024**2)


class Put(Scope):
    """Attach an existing artifact or admit one exclusive exact-byte media copy."""

    action: Literal["attach", "admit"]
    collection: ID
    expected_revision: int = Field(ge=1)
    evidence: Evidence


class Pin(Scope):
    """Protect a collection or one artifact from removal and LRU pruning."""

    action: Literal["pin"]
    collection: ID
    expected_revision: int = Field(ge=1)
    asset_id: ID | None = None
    pinned: bool


class Delete(Scope):
    """Remove inactive unpinned collection evidence or one unreferenced owned asset."""

    action: Literal["delete"]
    collection: ID
    expected_revision: int = Field(ge=1)
    asset_id: ID | None = None


class Prune(Scope):
    """Reclaim at most a finite number of unreferenced owned assets in LRU order."""

    action: Literal["prune"]
    target_bytes: int = Field(ge=1, le=1024**3)
    max_assets: int = Field(default=20, ge=1, le=100)


Request = Annotated[Configure | Create | Select | Read | Put | Pin | Delete | Prune,
                    Field(discriminator="action")]


class Response(CorpusModel):
    """Local receipts distinguish partial cleanup from successful reclamation."""

    status: Literal["configured", "created", "selected", "cleared", "listed", "recalled",
                    "health", "attached", "admitted", "pinned", "deleted", "pruned", "partial"]
    workspace: ID
    active_collection: ID | None = None
    collection: ID | None = None
    index_revision: int | None = None
    records: list[dict] = Field(default_factory=list)
    next_offset: int | None = None
    reclaimed_bytes: int = 0
    removed_observations: int = 0
    cleanup_liabilities: list[dict] = Field(default_factory=list)
    storage: dict = Field(default_factory=dict)
    provider_calls: Literal[0] = 0
