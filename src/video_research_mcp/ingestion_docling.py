"""One explicitly authorized local Docling conversion with pinned contract bytes."""

import hashlib
import json
import math
import time
from pathlib import Path

from .config import get_config
from .image_preprocessing import image_worker
from .ingestion_docling_document import parse_document
from .media_local_io import _open_regular
from .vision_http import exchange

MAX_RESPONSE_BYTES = 240 * 1024
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
OPTIONS = {"to_formats": "json", "image_export_mode": "embedded", "do_ocr": "false",
           "do_table_structure": "true", "include_images": "true", "target_type": "inbody",
           "abort_on_error": "true", "do_picture_description": "false",
           "do_picture_classification": "false", "do_code_enrichment": "false",
           "do_formula_enrichment": "false"}


def service_profile():
    """Require the operator's explicit deployment qualification before any connection."""
    service = get_config().docling_service
    if service is None:
        raise ValueError("Docling parser is disabled; configure DOCLING_SERVICE_JSON explicitly")
    if not service.runtime_qualified:
        raise ValueError("Docling deployment lacks the operator runtime qualification assertion")
    return {"service": service.model_dump(mode="json"), "options": dict(OPTIONS),
            "request_max_bytes": MAX_UPLOAD_BYTES, "response_max_bytes": MAX_RESPONSE_BYTES,
            "runtime_identity": "operator_assertion_unattested", "service_cancellation": "unverified",
            "versions": {"docling-serve": "1.36.0", "docling": "2.129.0", "docling-core": "2.96.0"}}


def multipart(source, directory, cancelled, deadline):
    """Bind exactly the retained source bytes to one finite multipart request."""
    from .image_preprocessing import check_worker

    check_worker(cancelled, deadline)
    path = directory.parent / ("original" + {"pdf": ".pdf", "docx": ".docx",
                                           "markdown": ".md", "html": ".html"}[source["format"]])
    if str(path) != source["path"]:
        raise ValueError("Docling source path differs from its retained original")
    with _open_regular(path) as reader:
        data = reader.read(MAX_UPLOAD_BYTES + 1)
    if (len(data) > MAX_UPLOAD_BYTES or len(data) != source["bytes"]
            or hashlib.sha256(data).hexdigest() != source["sha256"]):
        raise ValueError("Docling source exceeds 30 MiB or differs from its retained commitment")
    boundary = "vrm-docling-" + source["sha256"]
    while boundary.encode() in data:
        boundary += "x"
    parts = [(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n').encode()
             for key, value in OPTIONS.items()]
    source_format = "md" if source["format"] == "markdown" else source["format"]
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="from_formats"\r\n\r\n{source_format}\r\n').encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{path.name}"\r\n'
                  'Content-Type: application/octet-stream\r\n\r\n').encode() + data +
                 f'\r\n--{boundary}--\r\n'.encode())
    check_worker(cancelled, deadline)
    return boundary, b"".join(parts)


def finite_json(body):
    """Reject nonfinite service data and duplicate keys at the JSON boundary."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Docling JSON contains duplicate keys")
            result[key] = value
        return result

    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("Docling JSON contains a nonfinite number")
        return parsed

    return json.loads(body, object_pairs_hook=unique, parse_float=finite_float,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


async def parse_docling_source(source, directory, profile, deadline):
    """Retain every returned wire body and submission ambiguity, including failure."""
    receipt = {"upload_attempted": False, "remote_conversion": "not_submitted",
                "contract_capture": "unavailable", "response_capture": "unavailable",
                "automatic_retries": 0, "local_io": "no_exchange_started", "exchange_started": False}
    retain(directory, "docling-profile.json", profile)
    try:
        schema, limits = await contract(directory, profile, receipt, deadline)
        receipt.update(source_num_pages_before_upload="unknown", max_num_pages=limits["max_num_pages"])
        if source["bytes"] > MAX_UPLOAD_BYTES or (limits["max_file_size"] is not None
                and source["bytes"] > limits["max_file_size"]):
            raise ValueError("Docling retained source exceeds the admitted file byte limit; no source submitted")
        boundary, content = await image_worker(multipart, source, directory, deadline=deadline)
        if service_profile() != profile or time.monotonic() >= deadline:
            raise ValueError("Docling service selection/deadline changed before source submission")
        submission = {"source_sha256": source["sha256"], "source_bytes": source["bytes"],
            "source_path": source["path"], "serialized_request_sha256": hashlib.sha256(content).hexdigest(),
            "serialized_request_bytes": len(content), "options": profile["options"],
             "contract_sha256": hashlib.sha256(schema).hexdigest(),
             "source_num_pages_before_upload": "unknown", "max_num_pages": limits["max_num_pages"],
            "remote_conversion": "may_continue", "automatic_retries": 0}
        retain(directory, "docling-submission.json", submission)
        receipt.update(upload_attempted=True, remote_conversion="may_continue", phase="upload_exchange")
        status, body = await exchange(profile["service"]["base_url"].rstrip("/") + "/v1/convert/file",
            method="POST", local=True, headers={"Content-Type": "multipart/form-data; boundary=" + boundary},
            content=content, request_limit=32 * 1024 * 1024, response_limit=MAX_RESPONSE_BYTES)
        retain(directory, "docling-response.json", body)
        receipt.update(response_capture="complete", response_http_status=status, phase="interpretation")
        if status != 200:
            raise ValueError("Docling conversion HTTP failure; remote work may continue; no automatic retry")
        response = finite_json(body)
        if response["document"]["filename"] != Path(source["path"]).name:
            raise ValueError("Docling response filename differs from the submitted retained original")
        pages = response["document"]["json_content"].get("pages", {})
        if limits["max_num_pages"] is not None and len(pages) > limits["max_num_pages"]:
            raise ValueError("Docling reported page population exceeds contract max_num_pages")
        result = await image_worker(parse_document, response, directory, deadline=deadline)
        result.limitations.append("Source page count was unknown before upload; max_num_pages checked only against returned page population")
        receipt.update(outcome="success", remote_conversion="service_reported_success")
        return result
    except BaseException as error:
        receipt.update(outcome="failed_or_cancelled", error_type=type(error).__name__)
        raise
    finally:
        if receipt["exchange_started"]:
            receipt["local_io"] = "exchange_cleanup_awaited; socket_close_success_not_independently_attested"
        retain(directory, "docling-lifecycle.json", receipt)


def retain(directory, name, data):
    """Create immutable private evidence, preserving original service bytes."""
    body = data if isinstance(data, bytes) else json.dumps(data, allow_nan=False).encode()
    path = directory / name
    with path.open("xb") as writer:
        path.chmod(0o600)
        writer.write(body)


async def contract(directory, profile, receipt, deadline):
    """Verify the pinned primary capabilities contract before source transmission."""
    if service_profile() != profile or time.monotonic() >= deadline:
        raise ValueError("Docling service selection/deadline changed before contract check")
    service = profile["service"]
    receipt.update(phase="contract_exchange", exchange_started=True)
    status, body = await exchange(service["base_url"].rstrip("/") + service["contract_route"],
        method="GET", local=True, headers={}, content=b"", response_limit=MAX_RESPONSE_BYTES)
    retain(directory, "docling-contract.json", body)
    receipt.update(contract_capture="complete", contract_http_status=status)
    if status != 200 or hashlib.sha256(body).hexdigest() != service["expected_contract_sha256"]:
        raise ValueError("Docling contract unavailable or differs from pinned bytes; no source submitted")
    data = finite_json(body)
    validate_contract(data, profile["versions"])
    return body, data["limits"]


def validate_contract(data, versions):
    """Require the actual primary capabilities shape, versions and selected output route."""
    if (type(data) is not dict or type(data.get("versions")) is not dict
            or any(data["versions"].get(k) != v for k, v in versions.items())
            or any(type(data.get(k)) is not dict for k in ("targets", "features", "limits", "stages"))):
        raise ValueError("Docling capabilities shape or pinned versions differ")
    sequences = [data.get(k) for k in ("sources", "output_formats", "image_export_modes")]
    sequences.append(data["targets"].get("allowed"))
    if any(type(v) is not list or not all(type(x) is str for x in v) for v in sequences):
        raise ValueError("Docling capabilities require explicit string populations")
    if ("file" not in sequences[0] or "inbody" not in sequences[3] or "json" not in sequences[1] or "embedded" not in sequences[2]
            or type(data["targets"].get("default")) is not str
            or data["features"].get("api_key_required") is not False
            or type(data["features"].get("artifact_storage")) is not bool):
        raise ValueError("Docling capabilities require file input, inbody JSON/embedded and no API key")
    limits = data["limits"]
    if type(limits.get("max_sources_per_request")) is not int or limits["max_sources_per_request"] < 1:
        raise ValueError("Docling capabilities do not admit one source")
    for key in ("max_document_timeout", "max_images_scale"):
        value = limits.get(key)
        if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
            raise ValueError("Docling capability limits must be finite positive numbers")
    for key in ("max_num_pages", "max_file_size"):
        if key not in limits:
            raise ValueError("Docling capability page/file limits must be explicitly present")
        value = limits[key]
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError("Docling capability page/file limits must be positive integers")


def failure_evidence(source):
    """Bind retained wire/lifecycle files into the durable terminal failure."""
    directory = Path(source["path"]).parent / "derived"
    artifacts = {}
    lifecycle = {"remote_conversion": "not_submitted", "upload_attempted": False}
    paths = []
    for index, path in enumerate(directory.iterdir()):
        if index >= 64:
            raise ValueError("Docling failure artifact population exceeds limits")
        if (path.name.startswith("docling-") and path.suffix == ".json") or (
                path.name.startswith("docling-image-") and path.suffix == ".png"):
            paths.append(path)
    total = 0
    for path in sorted(paths):
        ceiling = 256 * 1024 if path.suffix == ".png" else MAX_RESPONSE_BYTES
        with _open_regular(path) as reader:
            body = reader.read(ceiling + 1)
        total += len(body)
        if len(body) > ceiling or total > 8 * 1024 * 1024:
            raise ValueError("Docling failure evidence exceeds its bounded receipt limit")
        artifacts[str(path)] = hashlib.sha256(body).hexdigest()
        if path.name == "docling-lifecycle.json":
            lifecycle = finite_json(body)
    if type(lifecycle) is not dict or type(lifecycle.get("upload_attempted")) is not bool:
        raise ValueError("Docling failure lifecycle is malformed")
    return {"docling_lifecycle": lifecycle, "docling_evidence": artifacts}, artifacts
