"""Optional original-grid segmentation proposals with exact raster artifacts.

Requirements are independently adapted from Qwen-MM-Plugins (Apache-2.0).
SAM's separate custom license, model access and runtime remain unattested.
"""

import asyncio
import hashlib
import os
import time

from .config import get_config
from .errors import make_tool_error
from .image_manifest import json_digest, write_manifest
from .image_preprocessing import MAX_ARTIFACT_BYTES, MAX_STILL_BYTES, image_worker
from .media_local_io import _open_regular
from .media_snapshot import checked_path, snapshot
from .models.segmentation import (
    SegmentationArtifact, SegmentationMask, SegmentationRequest, SegmentationResult,
)
from .segmentation_images import MAX_GRID_PIXELS, MAX_MASK_PIXELS, prepare, publish
from .segmentation_service import SegmentationError, selected_service, submit, unchanged


def source_preflight(file_path: str) -> str:
    """Apply the existing regular-file fence and 16 MiB ceiling before snapshot copy."""
    path = checked_path(file_path)
    with _open_regular(path) as reader:
        if not 0 < os.fstat(reader.fileno()).st_size <= MAX_STILL_BYTES:
            raise SegmentationError("source_byte_limit")
    return str(path)


def metadata(request, selected, source, artifacts, masks, response_sha) -> dict:
    """Bind observed raster bytes separately from operator model/checkpoint assertions."""
    profile, _ = selected
    artifacts = [SegmentationArtifact.model_validate(value).model_dump(mode="json") for value in artifacts]
    masks = [SegmentationMask.model_validate(value).model_dump(mode="json") for value in masks]
    request_json = request.model_dump(mode="json")
    service = {"service_id": request.service_id, **profile.model_dump(mode="json")}
    status = "planned" if request.dry_run else "complete"
    origin = "mock_fixture" if profile.origin == "mock-fixture" else "external_service_prediction"
    binding = {"request": request_json, "service": service, "source_sha256": source["sha256"],
               "artifacts": [a["sha256"] for a in artifacts], "response_sha256": response_sha,
               "engine": "owned_segmentation_wire_v1"}
    return {"status": status, "source": source, "artifact": artifacts[-1] if masks else artifacts[0],
            "artifacts": artifacts, "masks": masks, "num_masks": len(masks),
            "outcome": "planned" if request.dry_run else "mask_proposals" if masks else "abstention",
            "service": service, "readiness": {"transport": "not_contacted" if request.dry_run else "response_contract_validated",
            "model": "not_used_mock_fixture" if profile.origin == "mock-fixture" else "unattested_external_service",
            "checkpoint": "operator_declared_unattested" if profile.checkpoint_sha256 else "not_declared_unattested",
            "model_loaded_verified": False, "checkpoint_identity_verified": False,
            "model_weight_license_verified": False, "health_probe_performed": False},
            "request": request_json, "request_sha256": json_digest(request_json),
            "operation_sha256": json_digest(binding), "response_sha256": response_sha,
            "provenance": {"engine": "owned_segmentation_wire_v1", "preparation": "source_derived_rgb_png",
            "result_origin": None if request.dry_run else origin, "source_grid": "stored_untransformed_pixels",
            "coordinate_convention": "continuous_original_pixel_xyxy", "score": "uncalibrated_service_declaration",
            "inference_used": False if profile.origin == "mock-fixture" or request.dry_run else "external_service_unattested",
            "semantic_correctness_verified": False, "object_absence_verified": False, "human_review": "pending",
            "color_management_verified": False, "destructive_edit_performed": False},
            "warnings": ["Mask/box semantic correctness and score calibration are unverified.",
            "Service response validity does not attest model readiness, checkpoint identity or grants.",
            "RGB preparation strips metadata/profile/alpha; no crop, resize or orientation normalization."],
            "limits": {"max_source_bytes": MAX_STILL_BYTES, "max_grid_pixels": MAX_GRID_PIXELS,
            "max_masks": 16, "max_aggregate_mask_pixels": MAX_MASK_PIXELS, "max_http_response_bytes": 262144,
            "max_artifact_bytes": MAX_ARTIFACT_BYTES, "max_manifest_bytes": 131072,
            "max_request_bytes": 33554432, "http_timeout_seconds": 120, "cleanup_seconds": 5}}


async def workflow(request, selected, deadline, state) -> dict:
    """Join preparation, one optional exchange and exact original/artifact readbacks."""
    path = source_preflight(request.file_path)
    async with snapshot(path, request.expected_source_sha256) as owned:
        source, prepared, body = await image_worker(prepare, owned, deadline=deadline)
        await owned.verify()
        unchanged(request, selected)
        artifacts, masks, response_sha = [prepared], [], None
        if not request.dry_run:
            state["phase"] = "service"
            response, raw = await submit(request, selected, body)
            state["phase"] = "source_readback"
            await owned.verify()
            unchanged(request, selected)
            state["phase"] = "response"
            origin = "mock_fixture" if selected[0].origin == "mock-fixture" else "external_service_prediction"
            artifacts, masks = await image_worker(publish, response, request, owned, prepared, origin, deadline=deadline)
            response_sha = hashlib.sha256(raw).hexdigest()
        state["phase"] = "publication"
        value = metadata(request, selected, source, artifacts, masks, response_sha)
        await owned.verify()
        unchanged(request, selected)
        value["manifest"] = await write_manifest(value, owned.directory)
        value = SegmentationResult.model_validate(value).model_dump(mode="json")
        unchanged(request, selected)
    return value


async def segment_image(request: SegmentationRequest) -> dict:
    """Return bounded segmentation metadata or a fixed refusal without provider diagnostics."""
    state = {"phase": "request"}
    try:
        request = SegmentationRequest.model_validate(request)
        state["phase"] = "configuration"
        selected = selected_service(request)
        state["phase"] = "source"
        timeout = min(get_config().media_acquire_timeout_seconds, 120)
        async with asyncio.timeout(timeout):
            return await workflow(request, selected, time.monotonic() + timeout, state)
    except Exception as error:
        if isinstance(error, ImportError):
            value = make_tool_error(RuntimeError("Segmentation refused: images_dependency_missing"))
            return {**value, "category": "DEPENDENCY_MISSING", "reason": "images_dependency_missing",
                    "hint": "Install video-research-mcp[images] with the server's Python interpreter.", "retryable": False}
        reason = error.reason if isinstance(error, SegmentationError) else {
            "request": "request_invalid", "configuration": "service_configuration_invalid",
            "source": "source_refused", "source_readback": "source_changed",
            "response": "response_invalid", "publication": "artifact_or_source_changed",
            "service": "service_transport_failed"}[state["phase"]]
        value = make_tool_error(RuntimeError("Segmentation refused: " + reason))
        return {**value, "reason": reason, "retryable": False}
