"""Selected image lifecycle with durable intent and explicit recovery only.

Uses the existing Wan lease/CAS design with independently authored image bodies.
No DashScope SDK, generation retry, or invented synchronous polling endpoint is used.
"""

import asyncio
import base64
import hashlib
import json
from pathlib import Path
import re
import time
from uuid import uuid4

from .generation_assets import request_bytes
from .image_generation_assets import MAX_IMAGE_BYTES, acquire_images, verify_public_reference
from .image_generation_request import CONTRACT, adapter_revisions, freeze_request, provider_payload, read_operator_quote, selected_config, verify_sources
from .job_store import JobStore
from .models.image_generation import ImageGenerationRequest, ImageGenerationResult, ImageOperation, ImageTaskResponse
from .planning_sources import project_directory
from .redaction import redact_text
from .render_artifacts import verify_output

KIND = "dashscope_image_generation"


def _store() -> JobStore:
    """Bound controller artifact readbacks independently from recorded status."""
    deadline = time.monotonic() + 5

    def check():
        if time.monotonic() > deadline:
            raise TimeoutError("Image artifact readback deadline exceeded")

    return JobStore(readback_check=check, max_artifact_bytes=MAX_IMAGE_BYTES)


def _load(job_id: str) -> dict:
    """Require the selected kind and controller-verified frozen request/result."""
    row = _store().get(job_id)
    if not row or row["kind"] != KIND:
        raise ValueError("Image generation job not found")
    if (row["attestation"]["request_integrity"] != "verified"
            or row["attestation"]["result_integrity"] not in {"verified", "absent"}):
        raise ValueError("Image generation request/result integrity failed")
    return row


def _view(row: dict) -> dict:
    """Expose source/byte evidence without exposing expiring signed URLs."""
    state = dict(row["result"] or {})
    state.pop("image_urls", None)
    state.pop("response_body", None)
    if state.get("translation_message") is not None:
        state["translation_message"] = redact_text(state["translation_message"])
    status = row["status"]
    if status in {"queued", "running"}:
        status = "unknown"
    if status == "completed":
        assets = state.get("assets", [])
        if (not row["attestation"]["verified"] or len(assets) != row["request"]["generation"]["n"]
                or any(not verify_output(a, MAX_IMAGE_BYTES)
                       or a.get("qualification", {}).get("artifact_sha256") != a["sha256"]
                       or not a.get("qualification", {}).get("full_decode") for a in assets)):
            status = "unknown"
        try:
            verify_sources(Path(row["request"]["project_dir"]), row["request"]["generation"])
        except (OSError, ValueError):
            status = "unknown"
            state["source_readback"] = "MISMATCH_OR_UNAVAILABLE"
    return ImageGenerationResult(job_id=row["job_id"], status=status, recorded_status=row["status"],
            provider_request_id=state.get("provider_request_id"), provider_task_id=row["external_id"],
            request_sha256=row["request_sha256"], source_revision=row["source_revision"],
            state={**state, "request": row["request"]["generation"],
                   "live_provider": "UNQUALIFIED", "full_security_review": "UNRESOLVED"},
            artifact_hashes=row["artifact_hashes"], attestation=row["attestation"], error=row["error"]).model_dump(mode="json")


def _save(row: dict, owner: str, state: dict, status="unknown", *, release=False,
          external_id=None, artifact_hashes=None, error=None) -> None:
    """Refuse further work after failed lease/CAS ownership."""
    if not _store().checkpoint(row["job_id"], owner, status=status, result=state,
            release=release, external_id=external_id, artifact_hashes=artifact_hashes, error=error):
        raise RuntimeError("Image checkpoint ownership failed; external state remains UNKNOWN")


def _begin(row: dict, action: str, operation: ImageOperation) -> tuple[str, dict] | None:
    """Deduplicate explicit operation IDs under a durable finite lease."""
    if not operation.authorize or operation.principal != row["request"]["generation"]["operation"]["principal"]:
        raise ValueError("Explicit authorized operation with the frozen caller declaration required")
    state = row["result"] or {"operations": {}, "generation_intent_count": 0,
                              "post_attempt_count": 0, "poll_count": 0, "cancel_intent_count": 0, "assets": []}
    previous = state["operations"].get(operation.operation_id)
    if previous and previous != action:
        raise ValueError("Image operation ID is bound to another action")
    if previous or row["status"] in {"completed", "failed", "cancelled", "partial"}:
        return None
    if adapter_revisions() != row["request"]["adapter_revision"] or CONTRACT != row["request"]["contract"]:
        raise ValueError("Frozen image adapter changed; reconciliation required")
    base, _ = selected_config()
    if base != row["request"]["api_origin"]:
        raise ValueError("Image API origin changed")
    owner = uuid4().hex
    claimed = _store().claim(row["job_id"], owner, lease_seconds=240)
    if not claimed:
        return None
    state = claimed["result"] or state
    previous = state["operations"].get(operation.operation_id)
    if previous or (action == "submit" and state["generation_intent_count"]):
        _save(claimed, owner, state, release=True)
        if previous and previous != action:
            raise ValueError("Image operation ID conflicts")
        return None
    state["operations"][operation.operation_id] = action
    _save(claimed, owner, state)
    return owner, state


def _capture(row: dict, owner: str, state: dict, body: bytes, *, task=False) -> None:
    """Retain exact bounded provider bytes before fallible response interpretation."""
    state["response_body"] = base64.b64encode(body).decode("ascii")
    state["response_sha256"] = hashlib.sha256(body).hexdigest()
    _save(row, owner, state)
    value = json.loads(body)
    if task:
        response = ImageTaskResponse.model_validate(value)
        if row["external_id"] and response.output.task_id != row["external_id"]:
            raise ValueError("Provider translation task ID differs from durable task")
        state.setdefault("provider_request_id", response.request_id)
        state["last_provider_request_id"] = response.request_id
        state["provider_status"] = response.output.task_status
        state["translation_message"] = response.output.message
        if response.output.task_status == "SUCCEEDED":
            if not response.output.image_url:
                raise ValueError("Translation succeeded without an image URL")
            state["image_urls"] = [response.output.image_url]
        _save(row, owner, state, external_id=response.output.task_id)
    else:
        request_id = value.get("request_id")
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", request_id):
            raise ValueError("Synchronous image response lacks a valid provider request ID")
        state["provider_request_id"] = request_id
        choices = value.get("output", {}).get("choices", [])
        if len(choices) != 1 or choices[0].get("finish_reason") != "stop":
            raise ValueError("Synchronous image response is incomplete or ambiguous")
        message = choices[0]["message"]
        content = message["content"]
        if (message.get("role") != "assistant" or len(content) != row["request"]["generation"]["n"]
                or any(set(part) != {"image"} for part in content)):
            raise ValueError("Synchronous image response content differs from requested output")
        state["image_urls"] = [part["image"] for part in content]
        state["provider_status"] = "SUCCEEDED"
        _save(row, owner, state)


def _failure(row: dict, owner: str, state: dict, action: str, error: BaseException) -> None:
    """Retain ambiguity and previous failures without reclassifying an unknown effect."""
    state.setdefault("failures", []).append({"action": action, "type": type(error).__name__})
    _save(row, owner, state, release=True, error=f"{action}: {type(error).__name__}; reconciliation required")


async def _fetch_task(row: dict, owner: str, state: dict) -> None:
    """Count one real translation task fetch before HTTP and check exact origin/identity."""
    if state["poll_count"] >= row["request"]["generation"]["max_polls"]:
        raise ValueError("Translation poll budget exhausted")
    state["poll_count"] += 1
    _save(row, owner, state)
    base, key = selected_config()
    if base != row["request"]["api_origin"]:
        raise ValueError("Translation fetch origin changed")
    body = await request_bytes("GET", base + "/tasks/" + row["external_id"],
                               {"Authorization": "Bearer " + key}, None, 65536)
    _capture(row, owner, state, body, task=True)


async def submit_image_generation(project_id: str, request: ImageGenerationRequest) -> dict:
    """Create one logical job and at most one provider generation intent."""
    job_id = "image-" + request.logical_job_id
    existing = _store().get(job_id)
    if existing:
        row = _load(job_id)
        if row["request"]["project_id"] != project_id or row["request"]["generation"] != request.model_dump(mode="json"):
            raise ValueError("Existing logical image request differs from frozen request")
        return _view(row)
    frozen, source = freeze_request(project_id, request)
    row = _store().create(KIND, frozen, source, job_id=job_id, exclusive_key=job_id)
    begun = _begin(row, "submit", request.operation)
    if not begun:
        return _view(_load(job_id))
    owner, state = begun
    try:
        project = Path(frozen["project_dir"])
        if request.mode == "image_translate":
            await verify_public_reference(project, frozen["generation"]["references"][0])
        verify_sources(project, frozen["generation"])
        if read_operator_quote(project, request, frozen["api_origin"]) != frozen["quote"]:
            raise ValueError("Image quote changed before POST")
        payload = provider_payload(frozen)
        base, key = selected_config()
        if base != frozen["api_origin"]:
            raise ValueError("Image origin changed before POST")
        state["generation_intent_count"] = 1
        state["post_attempt_count"] = 1
        state["submission_intent_id"] = request.operation.operation_id
        _save(row, owner, state)
        asynchronous = request.mode == "image_translate"
        path = "/services/aigc/image2image/image-synthesis" if asynchronous else "/services/aigc/multimodal-generation/generation"
        headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
        if asynchronous:
            headers["X-DashScope-Async"] = "enable"
        body = await request_bytes("POST", base + path, headers, payload, 65536)
        _capture(row, owner, state, body, task=asynchronous)
        _save(_load(job_id), owner, state, release=True)
    except BaseException as error:
        _failure(row, owner, state, "submit", error)
        if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise
    return _view(_load(job_id))


async def recover_image_generation(job_id: str, operation: ImageOperation, *, finalize=False) -> dict:
    """Poll one real translation task or finalize captured synchronous output explicitly."""
    row = _load(job_id)
    action = "finalize" if finalize else "poll"
    begun = _begin(row, action, operation)
    if not begun:
        return _view(_load(job_id))
    owner, state = begun
    try:
        frozen = row["request"]
        project = project_directory(frozen["project_id"])
        if str(project) != frozen["project_dir"]:
            raise ValueError("Frozen image project moved")
        verify_sources(project, frozen["generation"])
        if not state.get("image_urls") and row["external_id"] and not finalize:
            await _fetch_task(row, owner, state)
        elif not state.get("image_urls") and state.get("response_body"):
            _capture(row, owner, state, base64.b64decode(state["response_body"], validate=True),
                     task=frozen["generation"]["mode"] == "image_translate")
        if state.get("image_urls"):
            if len(state["image_urls"]) != frozen["generation"]["n"]:
                raise ValueError("Provider image count differs from frozen request")
            async for artifact in acquire_images(project, job_id, state["image_urls"], frozen, state["assets"]):
                state["assets"].append(artifact)
                _save(row, owner, state, artifact_hashes={a["path"]: a["sha256"] for a in state["assets"]})
            verify_sources(project, frozen["generation"])
            _save(row, owner, state, "completed", release=True,
                  artifact_hashes={a["path"]: a["sha256"] for a in state["assets"]})
        elif state.get("provider_status") in {"FAILED", "CANCELED"}:
            _save(row, owner, state, "failed" if state["provider_status"] == "FAILED" else "cancelled", release=True)
        else:
            state["recovery_seam"] = ("Provider task requires explicit poll" if row["external_id"]
                else "No recoverable provider ID/response; synchronous remote reconciliation required; no resubmit")
            _save(row, owner, state, release=True)
    except BaseException as error:
        _failure(row, owner, state, action, error)
        if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise
    return _view(_load(job_id))


async def cancel_image_generation(job_id: str, operation: ImageOperation) -> dict:
    """Refuse synchronous cancellation; cancel only freshly PENDING translation with confirmation."""
    row = _load(job_id)
    begun = _begin(row, "cancel", operation)
    if begun:
        owner, state = begun
        try:
            if row["request"]["generation"]["mode"] != "image_translate":
                state["cancel_supported"] = False
                state["cancel_refused"] = "Synchronous image generation has no documented remote cancellation"
            elif not row["external_id"] or state["cancel_intent_count"]:
                state["cancel_refused"] = "No bound task or a cancellation intent already exists; reconcile without retry"
            else:
                verify_sources(Path(row["request"]["project_dir"]), row["request"]["generation"])
                await _fetch_task(row, owner, state)
                state["cancel_supported"] = True
                if state["provider_status"] == "PENDING":
                    if state["poll_count"] >= row["request"]["generation"]["max_polls"]:
                        raise ValueError("Cancellation confirmation fetch budget unavailable")
                    base, key = selected_config()
                    if base != row["request"]["api_origin"]:
                        raise ValueError("Translation cancellation origin changed")
                    state["cancel_intent_count"] = 1
                    state["cancel_intent_id"] = operation.operation_id
                    _save(row, owner, state)
                    body = await request_bytes("POST", base + "/tasks/" + row["external_id"] + "/cancel",
                                               {"Authorization": "Bearer " + key}, None, 65536)
                    ack = json.loads(body)
                    if not isinstance(ack, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", ack):
                        raise ValueError("Cancel ACK requires the official JSON-string request ID")
                    state["cancel_ack_request_id"] = ack
                    _save(row, owner, state)
                    await _fetch_task(row, owner, state)
                    state["cancellation_confirmed"] = state["provider_status"] == "CANCELED"
                else:
                    state["cancel_refused"] = "Only freshly PENDING translation tasks can be cancelled"
            _save(row, owner, state, "cancelled" if state.get("cancellation_confirmed") else "unknown", release=True)
        except BaseException as error:
            _failure(row, owner, state, "cancel", error)
            if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
    return _view(_load(job_id))
