"""Optional BYOK hosted service: one bounded request and an immutable local receipt."""

import asyncio
import json
import os
from datetime import datetime, timezone

from .config import get_config
from .models.search_provider import SearchExecution
from .models.twelvelabs import TwelveLabsError, TwelveLabsRequest, TwelveLabsResponse
from .provider_readiness import present
from .research_jobs import receipt
from .search_provider_results import ProviderFailure, digest
from .twelvelabs_jobs import finish, prepare, ready_asset, retained
from .twelvelabs_payloads import prepare_wire
from .twelvelabs_results import normalize
from .twelvelabs_routes import ROUTES
from .vision_http import exchange


def selection():
    """Read the explicit enable flag and selected key without borrowing another provider."""
    enabled = get_config().twelvelabs_enabled
    key = os.getenv("TWELVELABS_API_KEY", "").strip() if present(os.environ, "TWELVELABS_API_KEY") else ""
    return enabled, key


def error_result(error, state):
    """Withhold upstream diagnostics while preserving known attempts and unknown charges."""
    code, category = "invalid_twelvelabs_operation", "SCHEMA_VALIDATION_FAILED"
    if isinstance(error, ProviderFailure):
        code, category = error.code, error.category
    elif isinstance(error, PermissionError):
        code, category = "configuration_or_authority_missing", "PERMISSION_DENIED"
    elif isinstance(error, asyncio.CancelledError):
        code, category = "call_cancelled_outcome_unknown", "CANCELLED"
    elif isinstance(error, TimeoutError):
        code, category = "call_deadline_outcome_unknown", "NETWORK_ERROR"
    for call in state["execution"]["calls"]:
        if call["status"] == "attempted":
            call["status"] = "interrupted_unknown"
        call["result_status"] = "failed"
    return TwelveLabsError(error=code, category=category,
        hint="Read the retained receipt and reconcile the provider; automatic retry, polling and fallback are disabled",
        operation=state["operation"], request_sha256=state["request_sha256"], ids=state["ids"],
        media=state["media"], execution=state["execution"]).model_dump(mode="json")


async def dispatch(request, selected, wire, state, store, job, owner):
    """Reserve and record exactly one exchange before sending its authenticated bytes."""
    if selection() != selected:
        raise PermissionError("TwelveLabs account/configuration changed")
    method, url, headers, body, _media = wire
    call = {"operation": request.operation, "method": method, "status": "attempted", "result_status": "pending",
            "request_body_sha256": digest(body), "physical_requests": None,
            "physical_request_upper_bound": 1, "usage": None}
    state["execution"]["calls"].append(call)
    state["execution"].update(provider_requests_attempted=1, physical_requests=None, physical_request_upper_bound=1)
    pending = TwelveLabsError(error="call_reserved_outcome_unknown", category="NETWORK_ERROR",
        hint="Reconcile this recorded operation; never repeat an ambiguous submission",
        operation=request.operation, request_sha256=state["request_sha256"], ids=request.ids,
        media=state["media"], execution=state["execution"]).model_dump(mode="json")
    if not store.checkpoint(job["job_id"], owner, result=pending):
        raise RuntimeError("TwelveLabs attempt reservation lost ownership")
    async with asyncio.timeout(request.timeout_seconds):
        status, data = await exchange(url, headers=headers, content=body, method=method)
    call.update(status="response_received", http_status=status, received_bytes=len(data), response_sha256=digest(data))
    if selection() != selected:
        raise PermissionError("TwelveLabs account/configuration changed")
    if len(data) > request.max_response_bytes:
        raise ProviderFailure("response_byte_limit")
    if not 200 <= status < 300:
        category = "API_PERMISSION_DENIED" if status in {401, 403} else "API_QUOTA_EXCEEDED" if status == 429 else "NETWORK_ERROR"
        raise ProviderFailure(f"provider_http_{status}", category)
    result = normalize(data, request, state, selected[1], selected[0])
    call["result_status"] = "retained"
    body_data = result["provider_data"]
    call["usage"] = body_data.get("usage")
    if call["usage"] is None and isinstance(body_data.get("result"), dict):
        call["usage"] = body_data["result"].get("usage")
    result["execution"] = state["execution"]
    return result


async def execute(request: TwelveLabsRequest) -> dict:
    """Plan, perform, or read back one current service operation; never resubmit a job ID."""
    state = {"operation": None, "ids": {}, "request_sha256": None, "media": None,
             "execution": SearchExecution().model_dump(mode="json")}
    store, job, owner = None, None, ""
    try:
        request = TwelveLabsRequest.model_validate(request)
        state.update(operation=request.operation, ids=request.ids)
        selected = selection()
        if not request.dry_run and (not selected[0] or not selected[1] or not request.authorize_submission):
            raise PermissionError("Enable TwelveLabs, configure its BYOK credential and authorize this operation")
        if not request.dry_run and (ROUTES[request.operation][0] == "DELETE" or request.operation == "analysis_task_cancel") and not request.authorize_destruction:
            raise PermissionError("Deletion/cancellation requires separate destructive-operation authorization")
        wire = await prepare_wire(request, selected[1])
        state["media"] = wire[4]
        binding = {"request": request.model_dump(mode="json", exclude={"job_id"}),
                   "account_scope": digest(selected[1].encode()), "enabled": selected[0]}
        state["request_sha256"] = digest(json.dumps(binding, sort_keys=True, allow_nan=False).encode())
        if request.dry_run:
            return TwelveLabsResponse(operation=request.operation, status="planned", enabled=selected[0],
                request_sha256=state["request_sha256"], ids=request.ids, media=state["media"],
                observed_at=datetime.now(timezone.utc).isoformat(), execution=state["execution"]).model_dump(mode="json")
        ready_asset(request, binding["account_scope"])
        store, job, owner = prepare(request, binding)
        if not owner:
            if job["result"] is not None:
                return retained(job)
            state["execution"].update(physical_requests=None, physical_request_upper_bound=1)
            result = error_result(ProviderFailure("call_already_reserved_outcome_unknown"), state)
            return {**result, "job_receipt": receipt(job)}
        result = await dispatch(request, selected, wire, state, store, job, owner)
        return finish(store, job, owner, result)
    except (Exception, asyncio.CancelledError) as error:
        result = error_result(error, state)
        if owner:
            try:
                return finish(store, job, owner, result, unknown=bool(state["execution"]["provider_requests_attempted"]))
            except Exception:
                result["job_receipt"] = receipt(store.get(job["job_id"]))
        return result
