"""Exact primary image contracts, controls and immutable pre-effect admission."""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import re
from urllib.parse import urlsplit

from .config import get_config
from .image_generation_assets import image_data, raster, reference_bytes
from .materials import pinned_object
from .models.image_generation import ImageAccessDeclaration, ImageGenerationRequest, ImagePriceDeclaration, ImageQuote
from .planning_sources import digest, project_directory
from .render_storyboard_sources import confined_path, file_pin

CONTRACT = {
    "https://www.alibabacloud.com/help/en/model-studio/qwen-image-api":
        "7a20bc57dd1011562a1ab990021d07bf23d4856fb1057f6ad283bf0d6d056f69",
    "https://www.alibabacloud.com/help/en/model-studio/qwen-image-edit-api":
        "a4d5cdf692800f51ec5b59a9992ac03aae611abf39a18957ccb4e063e85b99c2",
    "https://www.alibabacloud.com/help/en/model-studio/qwen-mt-image-api":
        "680b35664d0624fe0d2321618973262ad188b89f5e0b6f40ce2a8d4294af520e",
    "https://www.alibabacloud.com/help/en/model-studio/manage-asynchronous-tasks":
        "3ba4affa5ca0393aea600dca5be84f5deee9ec6dbd105752d6d70c2d4fa1fb76",
}
CONTROL_FIELDS = ("size", "n", "seed", "prompt_extend", "watermark", "negative_prompt",
                  "source_lang", "target_lang", "image_segment")
SOURCE_LANGUAGES = {"zh", "en", "ja", "ko", "fr", "de", "es", "ru", "pt", "it", "vi", "auto"}
TARGET_LANGUAGES = {"zh", "en", "ja", "ko", "fr", "es", "ru", "pt", "it", "vi", "ms", "th", "id", "ar"}


def selected_config() -> tuple[str, str]:
    """Resolve the explicit image origin through a separately testable config binding."""
    cfg = get_config()
    from .materials_remote import public_url
    base, key = getattr(cfg, "dashscope_image_base_url", ""), cfg.dashscope_api_key
    if not base or not key:
        raise ValueError("Configure EXPLAINER_DASHSCOPE_IMAGE_BASE_URL and DashScope credential")
    parts = urlsplit(base)
    host = parts.hostname or ""
    if not re.fullmatch(r"[a-zA-Z0-9-]+\.(cn-beijing|ap-southeast-1)\.maas\.aliyuncs\.com", host):
        raise ValueError("Image endpoint requires the documented workspace origin")
    public_url(base, [host])
    if parts.path != "/api/v1" or parts.query:
        raise ValueError("Image API origin must end exactly in /api/v1 without query")
    return base, key


def adapter_revisions() -> dict:
    """Bind concrete image and shared collector/controller source bytes on every effect."""
    package = Path(__file__).parent
    names = ("image_generation.py", "image_generation_request.py", "image_generation_assets.py",
             "models/image_generation.py", "tools/image_generation.py", "generation_assets.py",
             "job_store.py", "materials.py", "materials_remote.py", "render_artifacts.py")
    return {name: file_pin((package / name).resolve(), 128 * 1024)["sha256"] for name in names}


def controls(request: dict) -> dict:
    """Retain the exact selected controls rather than inferring capability from context."""
    settings = {key: request[key] for key in CONTROL_FIELDS}
    if request["mode"] != "image_translate" and settings["watermark"] is None:
        settings["watermark"] = True
    return settings


def verify_sources(project: Path, request: dict) -> None:
    """Compare all source/reference/continuation and unaffected artifact hashes."""
    sources = [request["script"], request["scene"], *request["unaffected_artifacts"]]
    sources.extend(ref["source"] for ref in request["references"])
    if request["continuation"]:
        sources.append(request["continuation"])
    for source in sources:
        pin = file_pin(confined_path(project, source["path"]), 32 * 1024 * 1024)
        if pin["sha256"] != source["sha256"] or not pin["size_bytes"]:
            raise ValueError("Image source/reference/unaffected artifact integrity failed")
    if request["continuation"]:
        from .models.materials import PinnedFile

        prior = pinned_object(project, PinnedFile.model_validate(request["continuation"]))
        expected = {"model": request["model"], "controls": controls(request),
                    "references": request["references"],
                    "unaffected_artifacts": request["unaffected_artifacts"]}
        if prior != expected:
            raise ValueError("Continuation must bind exact image anchors, controls and unaffected artifacts")


def read_operator_quote(project: Path, request: ImageGenerationRequest, base: str) -> dict:
    """Check explicit model-specific per-image price/access/quote declarations."""
    from .materials_remote import public_url

    quote = ImageQuote.model_validate(pinned_object(project, request.quote))
    price = ImagePriceDeclaration.model_validate(pinned_object(project, quote.price_source))
    access = ImageAccessDeclaration.model_validate(pinned_object(project, quote.model_access_source))
    now = datetime.now(timezone.utc)
    if (quote.issued_at.tzinfo is None or quote.valid_until.tzinfo is None
            or not quote.issued_at <= now < quote.valid_until):
        raise ValueError("Image quote is expired, future or lacks timezone")
    value = request.model_dump(mode="json")
    value.pop("quote")
    if (quote.request_sha256 != digest(value) or quote.contract_sha256 != digest(CONTRACT)
            or quote.api_origin != base or quote.principal != request.operation.principal
            or quote.model != request.model or quote.mode != request.mode or quote.currency != request.currency):
        raise ValueError("Image quote differs from exact request/model/contract/principal")
    for evidence in (price, access):
        if (evidence.recorded_at.tzinfo is None or evidence.recorded_at > quote.issued_at
                or evidence.principal != quote.principal or evidence.model != quote.model):
            raise ValueError("Image declaration provenance differs from quote")
    public_url(price.source_url, ["www.alibabacloud.com", "help.aliyun.com"])
    public_url(access.source_url, [urlsplit(base).hostname])
    if (urlsplit(price.source_url).query or urlsplit(access.source_url).query
            or not urlsplit(price.source_url).path.startswith(("/help/en/model-studio/", "/en/model-studio/"))):
        raise ValueError("Image evidence requires exact primary-source provenance")
    if (price.mode != quote.mode or price.price_per_image != quote.price_per_image
            or price.currency != quote.currency or access.api_origin != base):
        raise ValueError("Image selected price/access differs from quote")
    total = quote.price_per_image * Decimal(request.n)
    if not total.is_finite() or total <= 0 or total > request.max_cost:
        raise ValueError("Image per-image total exceeds authorized cost bound")
    return {**quote.model_dump(mode="json"), "total_cost": str(total),
            "price_provenance": price.model_dump(mode="json"),
            "access_provenance": access.model_dump(mode="json"),
            "provider_verification": "UNQUALIFIED", "principal_authentication": "UNQUALIFIED"}


def freeze_request(project_id: str, request: ImageGenerationRequest) -> tuple[dict, str]:
    """Refuse unsupported intent and pin the actual request before any provider POST."""
    if not request.operation.authorize or not request.spend_authorized:
        raise ValueError("Explicit image operation and spend authorization required")
    if request.transparent_background:
        raise ValueError("Missing seam: selected primary image contracts do not document alpha control")
    project = project_directory(project_id)
    from PIL import Image
    value = request.model_dump(mode="json")
    verify_sources(project, value)
    if request.mode == "image_translate":
        if (request.model != "qwen-mt-image" or len(request.references) != 1
                or request.references[0].role != "input" or request.continuation):
            raise ValueError("Translation requires qwen-mt-image and one input; anchor/continuation seam unavailable")
        if (request.prompt or request.negative_prompt or request.size or request.seed is not None
                or request.prompt_extend or request.n != 1 or request.watermark is not None):
            raise ValueError("Translation has no documented prompt/size/seed/n/watermark control")
        if (request.source_lang not in SOURCE_LANGUAGES or request.target_lang not in TARGET_LANGUAGES
                or request.source_lang == request.target_lang
                or not {request.source_lang, request.target_lang} & {"en", "zh"}):
            raise ValueError("Unqualified translation language pair; legacy model requires Chinese or English")
        ref = value["references"][0]
        if not ref["public_url"]:
            raise ValueError("Missing seam: translation requires an already public image URL; no upload")
        info = raster(reference_bytes(project, ref["source"]))
        expected = [info["width"], info["height"]]
        if not all(15 <= p <= 8192 for p in expected) or not 0.1 <= expected[0] / expected[1] <= 10:
            raise ValueError("Translation input dimensions violate the primary contract")
    else:
        if (request.model != "qwen-image-2.0-pro" or not request.prompt.strip()
                or not request.size or request.source_lang or request.target_lang or request.image_segment):
            raise ValueError("Generation/edit require qwen-image-2.0-pro prompt and explicit size; translation intent unsupported")
        if len(request.prompt.encode("utf-8")) > 1300:
            raise ValueError("Prompt exceeds conservative UTF-8 bound; tokenizer/truncation seam unqualified")
        expected = [int(part) for part in request.size.split("*")]
        if any(p % 16 for p in expected) or not 512 * 512 <= expected[0] * expected[1] <= 2048 * 2048:
            raise ValueError("Image size must have documented pixel area and exact multiples of16")
        if request.mode == "text_to_image" and (request.references or request.continuation):
            raise ValueError("Text-to-image has no image anchor/continuation input; select image_edit")
        if request.mode == "image_edit" and not request.references:
            raise ValueError("Image edit requires one to three actual image anchors")
        for ref in value["references"]:
            if ref["public_url"]:
                raise ValueError("Edit uses pinned Base64 bytes; an additional URL intent is unsupported")
            raster(reference_bytes(project, ref["source"]))
    base, _ = selected_config()
    if request.mode == "image_translate" and not urlsplit(base).hostname.endswith(".cn-beijing.maas.aliyuncs.com"):
        raise ValueError("Selected legacy qwen-mt-image is documented only in Beijing")
    frozen = {"project_id": project_id, "project_dir": str(project), "api_origin": base,
              "generation": value, "contract": CONTRACT, "adapter_revision": adapter_revisions(),
              "quote": read_operator_quote(project, request, base), "expected_pixels": expected,
              "decoder_version": Image.__version__,
              "continuation_settings": {"model": request.model, "controls": controls(value),
                   "references": value["references"], "unaffected_artifacts": value["unaffected_artifacts"]}}
    return frozen, digest({"request": value, "contract": CONTRACT, "adapter": frozen["adapter_revision"]})


def provider_payload(frozen: dict) -> dict:
    """Compile exactly the selected documented HTTP body, retaining every supported control."""
    value = frozen["generation"]
    if value["mode"] == "image_translate":
        return {"model": value["model"], "input": {"image_url": value["references"][0]["public_url"],
                "source_lang": value["source_lang"], "target_lang": value["target_lang"],
                "ext": {"config": {"imageSegment": value["image_segment"]}}}}
    content = [{"image": image_data(Path(frozen["project_dir"]), ref["source"])}
               for ref in value["references"]]
    content.append({"text": value["prompt"]})
    settings = controls(value)
    params = {key: settings[key] for key in ("n", "size", "prompt_extend", "watermark", "negative_prompt")}
    if value["seed"] is not None:
        params["seed"] = value["seed"]
    return {"model": value["model"], "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": params}
