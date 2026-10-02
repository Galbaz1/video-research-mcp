"""Bounded optional hosted-service requests and attributed provider observations."""

import json
from string import Formatter
from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from .image_edit import Digest, Number, StrictModel
from .search_provider import SearchExecution, SourceLimits
from ..errors import ToolError
from ..twelvelabs_routes import ROUTES

Operation = Literal[*ROUTES]
Identifier = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_-]{1,128}$")]
IdentifierName = Literal["asset_id", "index_id", "indexed_asset_id", "task_id", "collection_id", "entity_id"]


class TwelveLabsRequest(SourceLimits):
    """Select one current REST operation without retries, polling or implicit disclosure."""

    operation: Operation
    ids: Annotated[dict[IdentifierName, Identifier], Field(max_length=6)] = {}
    parameters: Annotated[dict[str, JsonValue], Field(max_length=64)] = {}
    local_file: Annotated[str | None, Field(max_length=4096)] = None
    expected_source_sha256: Digest | None = None
    max_media_bytes: Annotated[int, Field(strict=True, ge=1, le=8 * 1024 * 1024)] = 8 * 1024 * 1024
    authorize_media_transfer: Annotated[bool, Field(strict=True)] = False
    authorize_destruction: Annotated[bool, Field(strict=True)] = False
    job_id: Annotated[str | None, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")] = None
    ready_asset_job_id: Annotated[str | None, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")] = None

    @model_validator(mode="after")
    def admitted(self):
        """Reject path interpolation and oversized payloads before any service dispatch."""
        path = ROUTES[self.operation][1]
        required = {name for _, name, _, _ in Formatter().parse(path) if name}
        if set(self.ids) != required:
            raise ValueError("Provide exactly the identifiers required by the selected route")
        if len(json.dumps(self.parameters, allow_nan=False, ensure_ascii=False).encode()) > 64 * 1024:
            raise ValueError("TwelveLabs parameters exceed 64 KiB")
        if (self.local_file is None) != (self.expected_source_sha256 is None):
            raise ValueError("Local media requires its expected source SHA256")
        if self.local_file is not None and self.operation not in {"asset_create", "search_text_image_composed_entity"}:
            raise ValueError("Local bytes are supported only by asset creation and image search")
        return self


class ProviderClip(StrictModel):
    """Exact returned seconds and provider IDs; no source-byte or factual attestation."""

    index_id: Identifier
    video_id: Identifier
    start: Annotated[Number, Field(ge=0)]
    end: Annotated[Number, Field(gt=0)]
    rank: Annotated[int | None, Field(strict=True, ge=0)] = None
    provider_reference: str
    source_reference_origin: Literal["provider_identifiers_and_offsets"] = "provider_identifiers_and_offsets"
    source_bytes_verified: Literal[False] = False

    @model_validator(mode="after")
    def interval(self):
        """Reject impossible returned intervals instead of repairing their clock."""
        if self.end <= self.start:
            raise ValueError("Provider clip end must exceed start")
        return self


class TwelveLabsResponse(StrictModel):
    """Keep successful transport, remote task status and complete generation separate."""

    provider: Literal["twelvelabs"] = "twelvelabs"
    operation: Operation
    status: Literal["planned", "complete", "partial", "processing", "ready", "failed", "canceled", "unknown"]
    request_sha256: Digest
    ids: dict[IdentifierName, Identifier] = {}
    provider_status: Annotated[str | None, Field(max_length=64)] = None
    provider_data: dict[str, JsonValue] | None = None
    provider_response_sha256: Digest | None = None
    observed_at: str
    clips: Annotated[list[ProviderClip], Field(max_length=50)] = []
    rejections: Annotated[list[dict], Field(max_length=50)] = []
    media: dict | None = None
    enabled: bool
    job_receipt: dict | None = None
    execution: SearchExecution
    source_content_role: Literal["data"] = "data"
    external_mcp_discovery_verified: Literal[False] = False
    source_verified_truth: Literal[False] = False
    entity_identity_verified: Literal[False] = False
    factual_success: Literal[False] = False


class TwelveLabsError(ToolError):
    """Preserve failed and interrupted attempts without exposing upstream secrets."""

    provider: Literal["twelvelabs"] = "twelvelabs"
    operation: Operation | None = None
    request_sha256: Digest | None = None
    ids: dict[IdentifierName, Identifier] = {}
    media: dict | None = None
    job_receipt: dict | None = None
    execution: SearchExecution
