"""Explicit model/account-bound temporary video upload without automatic fallbacks."""

import json
import uuid
from urllib.parse import urlencode, urlsplit

import httpx

from .vision_preparation import read_payload

_FIELDS = ("upload_dir", "upload_host", "oss_access_key_id", "signature", "policy",
           "x_oss_object_acl", "x_oss_forbid_overwrite")


def _policy(data):
    """Accept a bounded official policy without forwarding inference credentials to OSS."""
    body = json.loads(data)
    policy = body.get("data") if isinstance(body, dict) else None
    if not isinstance(policy, dict) or any(not isinstance(policy.get(f), str) or not policy[f] or len(policy[f]) > 16384 for f in _FIELDS):
        raise ValueError("Temporary upload policy is missing bounded required fields")
    host = urlsplit(policy["upload_host"])
    if host.scheme != "https" or not host.hostname or not host.hostname.endswith(".aliyuncs.com") or host.username or host.password or host.query or host.fragment:
        raise PermissionError("Temporary upload policy does not select an official HTTPS OSS origin")
    if host.port not in (None, 443) or not policy["upload_dir"].strip("/") or any(c in policy["upload_dir"] for c in "?#\\\r\n"):
        raise ValueError("Temporary upload policy has an invalid origin/object directory")
    return policy


async def upload_videos(profile, credential, parts, calls, grant):
    """Submit only expressly selected full videos, tied to the same inference account/model."""
    from .vision_http import exchange
    if not grant or not credential:
        raise PermissionError("Temporary video upload requires this workflow's explicit submission grant and configured credential")
    receipts, submitted = [], []
    for part in parts:
        if part["kind"] != "video":
            submitted.append(part)
            continue
        query = urlencode({"action": "getPolicy", "model": profile.model})
        call = {"kind": "upload_policy", "status": "attempted_usage_unknown",
                "origin": profile.upload_policy_url, "model": profile.model}
        calls.append(call)
        status, data = await exchange(profile.upload_policy_url + "?" + query,
            headers={"Authorization": "Bearer " + credential}, content=b"", method="GET")
        call["http_status"] = status
        if status != 200:
            raise RuntimeError(f"Temporary policy returned HTTP {status}; response body is withheld")
        call["status"] = "completed"
        policy = _policy(data)
        name = uuid.uuid4().hex + ".mp4"
        key = policy["upload_dir"].rstrip("/") + "/" + name
        form = {"OSSAccessKeyId": policy["oss_access_key_id"], "Signature": policy["signature"],
                "policy": policy["policy"], "x-oss-object-acl": policy["x_oss_object_acl"],
                "x-oss-forbid-overwrite": policy["x_oss_forbid_overwrite"],
                "key": key, "success_action_status": "200"}
        request = httpx.Request("POST", policy["upload_host"], data=form,
                               files={"file": (name, read_payload(part), "video/mp4")})
        content = request.read()
        receipt = {"source_sha256": part["sha256"], "source_bytes": part["bytes"],
                   "source_index": part["source_index"], "provider_url": "oss://" + key,
                   "policy_origin": profile.upload_policy_url, "inference_origin": profile.base_url,
                   "upload_origin": policy["upload_host"],
                   "model": profile.model, "status": "attempted_upload_unknown",
                   "retention_verified": False, "deletion_verified": False,
                   "expiry_seconds": None, "region_availability": "unverified",
                   "authorization": "explicit_current_workflow_submission"}
        receipts.append(receipt)
        call = {"kind": "video_upload", "status": "attempted_usage_unknown", "receipt": receipt}
        calls.append(call)
        status, data = await exchange(policy["upload_host"],
            headers={"Content-Type": request.headers["content-type"]}, content=content, method="POST")
        call["http_status"] = status
        if status != 200:
            raise RuntimeError(f"Temporary upload returned HTTP {status}; response body is withheld")
        call["status"] = "completed"
        receipt["status"] = "uploaded"
        submitted.append({**part, "provider_url": receipt["provider_url"]})
    return submitted, receipts
