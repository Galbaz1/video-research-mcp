"""One optional SAM-compatible HTTP submission through the existing peer fence.

Wire requirements credit Qwen-MM-Plugins at its recorded Apache-2.0 pin.
No foreign launcher, model, checkpoint, SDK or native framework is imported.
"""

import base64
import json
import os

from .config import get_config
from .image_manifest import canonical
from .models.segmentation import SegmentationService
from .vision_http import exchange


class SegmentationError(Exception):
    """Carry a fixed local reason without provider bodies, secrets or diagnostics."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def selected_service(request) -> tuple[SegmentationService, str | None]:
    """Read only the explicitly selected operator profile and environment credential."""
    profile = get_config().segmentation_services.get(request.service_id)
    if profile is None:
        raise SegmentationError("service_missing")
    profile = SegmentationService.model_validate(profile.model_dump())
    credential = os.environ.get(profile.api_key_env) if profile.api_key_env else None
    if profile.api_key_env and not credential:
        raise SegmentationError("credential_missing")
    if credential and any(ord(char) < 32 or ord(char) > 126 for char in credential):
        raise SegmentationError("credential_invalid")
    if not request.dry_run and not request.submission_authorized:
        raise SegmentationError("submission_not_authorized")
    return profile, credential


def unchanged(request, selected) -> None:
    """Refuse concurrent operator-profile or credential changes before publication."""
    if selected_service(request) != selected:
        raise SegmentationError("service_configuration_changed")


async def submit(request, selected, image: bytes) -> tuple[dict, bytes]:
    """Make one admitted POST, never using health words as readiness or retrying."""
    unchanged(request, selected)
    profile, credential = selected
    body = canonical({"image_b64": base64.b64encode(image).decode("ascii"),
                      "prompt": request.prompt, "return_img": True})
    headers = {"Content-Type": "application/json"}
    if credential:
        headers["Authorization"] = "Bearer " + credential
    try:
        status, raw = await exchange(profile.base_url.rstrip("/") + "/segment",
                                     headers=headers, content=body, method="POST", local=profile.local)
    except TimeoutError:
        raise SegmentationError("service_timeout") from None
    except Exception:
        raise SegmentationError("service_transport_failed") from None
    if not 200 <= status < 300:
        raise SegmentationError("service_http_error")
    try:
        response = json.loads(raw)
    except (ValueError, UnicodeError):
        raise SegmentationError("response_json_invalid") from None
    return response, raw
