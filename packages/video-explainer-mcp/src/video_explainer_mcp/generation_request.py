"""Selected official contract, source bindings and pre-spend admission."""

from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit
from pydantic import ValidationError

from .config import get_config
from .generation_references import I2V_WIRE_MODEL, freeze_references, provider_media
from .materials import pinned_object
from .models.generation import GenerationRequest, OperatorQuote, PriceDeclaration, ModelAccessDeclaration
from .planning_sources import digest, project_directory
from .render_storyboard_sources import confined_path, file_pin

CONTRACT = {
    "text-to-video-api-reference": "98048c9d7aed2acd3c860233ba6d9c13a8b6d38233dab38dfa9319a59427dd5c",
    "image-to-video-general-api-reference": "e22e9900dae43a8f22f7188f141228b960cc1ff9f3999a4d2caf2480ca20a0dc",
    "manage-asynchronous-tasks": "a836bc4a12da0623fd9c32616919f75819bca472f3a7a19858d0a7936e05d7a3",
}
PIXELS = {
    "720P": {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (960, 960),
             "4:3": (1104, 832), "3:4": (832, 1104)},
    "1080P": {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1440, 1440),
              "4:3": (1648, 1248), "3:4": (1248, 1648)},
}
RESULT_HOST = "dashscope-result-sh.oss-accelerate.aliyuncs.com"


def selected_config() -> tuple[str, str]:
    """Resolve only explicit credentials and a documented workspace API origin."""
    cfg = get_config()
    key = getattr(cfg, "dashscope_api_key", "")
    base = getattr(cfg, "dashscope_base_url", "")
    if not key or not base:
        raise ValueError("Selected DashScope credential and endpoint are not configured")
    parts = urlsplit(base)
    host = parts.hostname or ""
    if not re.fullmatch(r"[a-zA-Z0-9-]+\.(cn-beijing|ap-southeast-1)\.maas\.aliyuncs\.com", host):
        raise ValueError("Selected Wan2.7 endpoint must use a documented workspace origin")
    from .materials_remote import public_url

    public_url(base, [host])
    if parts.path != "/api/v1" or parts.query:
        raise ValueError("Selected endpoint must end exactly in /api/v1 without query")
    return base, key


def read_operator_quote(project: Path, request: GenerationRequest, base: str) -> dict:
    """Validate exact selected operator declarations and calculate the bounded total."""
    try:
        quote = OperatorQuote.model_validate(pinned_object(project, request.quote))
        price = PriceDeclaration.model_validate(pinned_object(project, quote.price_source))
        access = ModelAccessDeclaration.model_validate(pinned_object(project, quote.model_access_source))
    except ValidationError:
        raise ValueError("Selected operator declaration schema is invalid; price/access remain UNKNOWN") from None
    now = datetime.now(timezone.utc)
    if (quote.issued_at.tzinfo is None or quote.valid_until.tzinfo is None
            or not quote.issued_at <= now < quote.valid_until):
        raise ValueError("Selected operator quote is expired, future or lacks absolute time")
    body = request.model_dump(mode="json")
    body.pop("quote")
    if (quote.api_origin != base or quote.model != request.model or quote.resolution != request.resolution
            or quote.currency != request.currency or quote.principal != request.operation.principal
            or quote.request_sha256 != digest(body) or quote.contract_sha256 != digest(CONTRACT)):
        raise ValueError("Selected operator quote differs from exact caller/request/source contract")
    try:
        from .materials_remote import public_url

        public_url(price.source_url, ["www.alibabacloud.com", "help.aliyun.com"])
        public_url(access.source_url, [urlsplit(base).hostname])
    except ValueError:
        raise ValueError("Operator evidence has invalid primary-source URL provenance") from None
    if (urlsplit(price.source_url).query or urlsplit(access.source_url).query
            or not urlsplit(price.source_url).path.startswith(("/help/en/model-studio/", "/en/model-studio/"))):
        raise ValueError("Operator evidence must identify exact primary-source provenance without query credentials")
    for evidence in (price, access):
        if (evidence.recorded_at.tzinfo is None or evidence.recorded_at > quote.issued_at
                or evidence.principal != quote.principal or evidence.model != quote.model):
            raise ValueError("Operator evidence source/principal/time provenance differs from quote")
    if (price.resolution != quote.resolution or price.currency != quote.currency
            or price.price_per_second != quote.price_per_second or access.api_origin != base):
        raise ValueError("Operator selected price/access evidence differs from quote")
    total = quote.price_per_second * Decimal(request.duration)
    if not total.is_finite() or total <= 0 or total > request.max_cost:
        raise ValueError("Operator-declared total exceeds caller cost bound")
    return {**quote.model_dump(mode="json"), "total_cost": str(total),
            "quote_source": request.quote.model_dump(), "price_provenance": price.model_dump(mode="json"),
            "access_provenance": access.model_dump(mode="json"),
            "provider_verification": "UNQUALIFIED", "principal_authentication": "UNQUALIFIED"}


def verify_sources(project: Path, request: dict) -> None:
    """Verify every declared local source against its exact immutable commitment."""
    refs = [request["script"], request["scene"]]
    refs.extend(ref["source"] for ref in request["references"])
    if request["continuation"]:
        refs.append(request["continuation"])
    for ref in refs:
        pin = file_pin(confined_path(project, ref["path"]), 20 * 1024 * 1024)
        if pin["sha256"] != ref["sha256"] or not pin["size_bytes"]:
            raise ValueError("Generation source/reference integrity failed")


def adapter_revisions() -> dict[str, str]:
    """Bind the concrete files used for new effects and resume compatibility."""
    package = Path(__file__).parent
    return {name: file_pin((package / name).resolve(), 128 * 1024)["sha256"] for name in (
        "generation.py", "generation_request.py", "generation_assets.py", "generation_references.py",
        "models/generation.py", "tools/generation.py", "job_store.py", "render_artifacts.py")}


def freeze_request(project_id: str, request: GenerationRequest) -> tuple[dict, str]:
    """Freeze actual adapter/source bytes and exact selected parameters before POST."""
    if not request.operation.authorize or not request.spend_authorized:
        raise ValueError("Explicit submit operation and spend authorization are required")
    if not request.prompt.strip():
        raise ValueError("Generation prompt must contain text")
    if request.transparent_background:
        raise ValueError("Selected video model does not support transparent background")
    if request.model == "wan2.7-t2v" and (request.references or request.continuation):
        raise ValueError("Selected text-to-video model does not support these references or continuation")
    if request.model == "wan2.7-t2v" and request.expected_dimensions is not None:
        raise ValueError("Selected text-to-video dimensions are fixed by resolution and ratio")
    if request.expected_audio != "present":
        raise ValueError("Selected contract has no qualified silent-output control")
    project = project_directory(project_id)
    value = request.model_dump(mode="json")
    verify_sources(project, value)
    references = freeze_references(project, value) if request.model == "wan2.7-i2v" else None
    base, _ = selected_config()
    quote = read_operator_quote(project, request, base)
    revisions = adapter_revisions()
    envelope = {"provider": "dashscope", "project_id": project_id, "project_dir": str(project),
                "api_origin": base, "generation": value, "contract": CONTRACT,
                "adapter_revision": revisions, "quote": quote,
                "expected_pixels": (list(request.expected_dimensions) if references is not None
                                    else list(PIXELS[request.resolution][request.ratio]))}
    source = {"script": value["script"], "scene": value["scene"],
              "adapter_revision": revisions, "contract": CONTRACT}
    if references is not None:
        envelope.update(wire_model=I2V_WIRE_MODEL, reference_metadata=references,
                        mode="first_last_frame" if len(references) == 2 else "first_frame",
                        dimension_basis="caller_declared_i2v_output_not_provider_guarantee")
        source.update(references=value["references"], wire_model=I2V_WIRE_MODEL,
                      reference_metadata=references, expected_dimensions=list(request.expected_dimensions))
    return envelope, digest(source)


def provider_payload(request: dict) -> dict:
    """Encode only the pinned selected wire, comparing sources and origin before POST."""
    value = request["generation"]
    project = Path(request["project_dir"])
    inputs = {"prompt": value["prompt"], "negative_prompt": value["negative_prompt"]}
    parameters = {"duration": value["duration"], "resolution": value["resolution"],
                  "seed": value["seed"], "prompt_extend": value.get("prompt_extend", False),
                  "watermark": value.get("watermark", True)}
    model = value["model"]
    if model == "wan2.7-i2v":
        if request["wire_model"] != I2V_WIRE_MODEL:
            raise ValueError("Selected I2V wire model differs from the frozen contract")
        inputs["media"] = provider_media(project, value, request["reference_metadata"])
        model = I2V_WIRE_MODEL
    else:
        parameters["ratio"] = value["ratio"]
    verify_sources(project, value)
    if request["contract"] != CONTRACT or request["adapter_revision"] != adapter_revisions():
        raise ValueError("Generation adapter or contract changed before POST")
    if selected_config()[0] != request["api_origin"]:
        raise ValueError("Submit origin differs from the frozen request")
    return {"model": model, "input": inputs, "parameters": parameters}
