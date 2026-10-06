"""Explicit source, rights and ordered material assembly requests."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

STOCK_CREDENTIAL_ENV = {"pexels": "PEXELS_API_KEY", "pixabay": "PIXABAY_API_KEY"}

Sha = str


class PinnedFile(BaseModel):
    """An existing project file and its caller-observed exact digest."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    path: str = Field(min_length=1, max_length=240)
    sha256: Sha = Field(pattern=r"^[a-f0-9]{64}$")


class MaterialRights(BaseModel):
    """Caller retained rights declaration; application licenses grant no media rights."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    source_sha256: Sha = Field(pattern=r"^[a-f0-9]{64}$")
    source_url: str = Field(min_length=1, max_length=2048)
    license: str = Field(min_length=1, max_length=200)
    license_url: str = Field(min_length=1, max_length=2048)
    credit: str = Field(min_length=1, max_length=500)
    retrieved_at: datetime
    valid_until: datetime
    principal: str = Field(min_length=1, max_length=100)
    clip_use_allowed: bool

    @model_validator(mode="after")
    def aware_dates(self):
        """Require absolute UTC-compatible rights times."""
        if self.retrieved_at.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValueError("Rights times require timezone offsets")
        if self.license.strip().lower() in {"", "unknown", "pending", "unlicensed"} or not self.credit.strip():
            raise ValueError("An explicit asset license and credit are required")
        return self


class MaterialClip(BaseModel):
    """A scene/script binding to an existing exact local asset."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    scene_id: str = Field(min_length=1, max_length=100)
    script_id: str = Field(min_length=1, max_length=100)
    source: PinnedFile
    rights: PinnedFile
    kind: Literal["video", "image"] = "video"
    motion: Literal["still", "zoom"] = "still"
    use: Literal["illustrative", "evidentiary"] = "illustrative"
    evidence_packet: PinnedFile | None = None
    evidence_source_id: str | None = Field(default=None, max_length=100)
    start_seconds: float = Field(default=0, ge=0, le=3600, allow_inf_nan=False)
    duration_seconds: float = Field(gt=0, le=120, allow_inf_nan=False)
    fit: Literal["cover", "contain"] = "cover"


class MaterialsRequest(BaseModel):
    """A finite ordered silent visual assembly, without inferred scene matching."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    principal: str = Field(min_length=1, max_length=100)
    clips: list[MaterialClip] = Field(min_length=1, max_length=16)
    resolution: Literal["720p", "1080p"] = "720p"
    fps: Literal[24, 25, 30] = 30

    @model_validator(mode="after")
    def unique_scenes(self):
        """Reject ambiguous repeated scene bindings and excessive total duration."""
        if len({c.scene_id for c in self.clips}) != len(self.clips):
            raise ValueError("Scene IDs must be unique")
        if sum(c.duration_seconds for c in self.clips) > 300:
            raise ValueError("Assembly duration exceeds300seconds")
        return self


class StockConfig(BaseModel):
    """An explicitly configured source and caller authority, read from a pinned file."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    provider: Literal["pexels", "pixabay"]
    api_key_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,99}$")
    download_hosts: list[str] = Field(min_length=1, max_length=8)
    principal: str = Field(min_length=1, max_length=100)
    search_allowed: bool = False
    download_allowed: bool = False
    valid_until: datetime

    @model_validator(mode="after")
    def provider_credential_slot(self):
        """Keep the public field pinned to the selected provider's server credential slot."""
        if self.api_key_env != STOCK_CREDENTIAL_ENV[self.provider]:
            raise ValueError("Stock credential slot must match the selected provider")
        return self


class StockSearch(BaseModel):
    """Bounded stock search with an explicit source configuration."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    config: PinnedFile
    principal: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1, max_length=200)
    page: int = Field(default=1, ge=1, le=100)
    pages: int = Field(default=1, ge=1, le=3)


class StockDownload(BaseModel):
    """An exact remote rendition, with independent source and clip-use authority."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    config: PinnedFile
    rights: PinnedFile
    principal: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=2048)
    expected_sha256: Sha = Field(pattern=r"^[a-f0-9]{64}$")


class StockCandidate(BaseModel):
    """Bounded provider metadata that makes no clip-use or factual grant."""

    provider: Literal["pexels", "pixabay"]
    asset_id: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=2048)
    source_page: str | None = Field(default=None, max_length=2048)
    creator: str | None = Field(default=None, max_length=200)
    duration_seconds: float = Field(gt=0, le=14400, allow_inf_nan=False)
    width: int = Field(gt=0, le=16384)
    height: int = Field(gt=0, le=16384)
    use: Literal["illustrative"] = "illustrative"
    rights_status: Literal["not_granted_by_search"] = "not_granted_by_search"
