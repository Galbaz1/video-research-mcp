"""Explicit compatible text profiles and bounded structured generation contracts."""

import json
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from .image_edit import Number, StrictModel
from ..errors import ToolError

Capability = Literal["text", "structured_json", "images", "video", "audio", "files",
                     "grounding", "embeddings", "rerank"]
TEXT_CAPABILITIES = {"text", "structured_json"}


class TextBackend(StrictModel):
    """Operator-selected regional DashScope or literal loopback text endpoint."""

    provider: Literal["dashscope", "local_compatible"] = "dashscope"
    base_url: Annotated[str, Field(min_length=1, max_length=2048)]
    model: Annotated[str, Field(min_length=1, max_length=256)]
    api_key_env: Annotated[str | None, Field(pattern=r"^[A-Z][A-Z0-9_]*API_KEY$")] = None
    structured_format: Literal["json_object", "json_schema"] = "json_object"

    @model_validator(mode="after")
    def selected_origin(self):
        """Reject origin substitution and require the selected region's credential."""
        p = urlsplit(self.base_url)
        if not p.hostname or p.username is not None or p.password is not None or p.query or p.fragment or any(ord(c) <= 32 or ord(c) == 127 for c in self.base_url):
            raise ValueError("Text origin requires a host without credentials/query/fragment")
        if p.port is not None and not 1 <= p.port <= 65535:
            raise ValueError("Text origin port is invalid")
        if self.provider == "local_compatible":
            if p.scheme not in {"http", "https"} or p.hostname not in {"127.0.0.1", "::1"}:
                raise ValueError("Local text requires literal configured loopback")
        else:
            pattern = r"[a-zA-Z0-9-]+\.(ap-southeast-1|us-east-1|cn-beijing|cn-hongkong|eu-central-1)\.maas\.aliyuncs\.com"
            if p.scheme != "https" or not re.fullmatch(pattern, p.hostname) or p.port not in (None, 443) or p.path.rstrip("/") != "/compatible-mode/v1" or not self.api_key_env:
                raise ValueError("DashScope text requires exact workspace regional HTTPS origin and api_key_env")
        return self


class TextRequest(StrictModel):
    """One structured text submission; declared caps never imply unknown token prices."""

    backend: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    instruction: Annotated[str, Field(min_length=1, max_length=8192)]
    context: Annotated[str, Field(max_length=32768)] = ""
    output_schema: dict
    required_capabilities: Annotated[list[Capability], Field(max_length=9)] = ["text", "structured_json"]
    dry_run: Annotated[bool, Field(strict=True)] = True
    authorize_submission: Annotated[bool, Field(strict=True)] = False
    max_output_tokens: Annotated[int, Field(strict=True, ge=1, le=8192)] = 2048
    max_input_tokens: Annotated[int | None, Field(strict=True, ge=1)] = None
    max_total_tokens: Annotated[int | None, Field(strict=True, ge=1)] = None
    max_cost_usd: Annotated[Number | None, Field(gt=0)] = None
    timeout_seconds: Annotated[Number, Field(gt=0, le=120)] = 60

    @model_validator(mode="after")
    def inline_schema(self):
        """Keep validation local and schema work finite before any transmission."""
        import jsonschema
        from ..schema_guard import check_schema_complexity

        body = json.dumps(self.output_schema, allow_nan=False).encode()
        if len(body) > 32768 or self.output_schema.get("type") != "object":
            raise ValueError("Text schema requires an inline object schema within 32 KiB")
        pending = [self.output_schema]
        while pending:
            value = pending.pop()
            if not isinstance(value, dict):
                continue
            if any(k in value for k in ("$ref", "$dynamicRef", "$recursiveRef")):
                raise ValueError("Text schemas require inline definitions; references are unsupported")
            if "pattern" in value or "patternProperties" in value:
                raise ValueError("Text schemas cannot use regex validation")
            for key in ("properties", "$defs", "definitions", "dependentSchemas"):
                if isinstance(value.get(key), dict):
                    pending.extend(value[key].values())
            for key in ("items", "additionalProperties", "contains", "propertyNames", "not", "if", "then", "else", "unevaluatedItems", "unevaluatedProperties", "contentSchema"):
                if isinstance(value.get(key), (dict, bool)):
                    pending.append(value[key])
            for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
                if isinstance(value.get(key), list):
                    pending.extend(value[key])
        jsonschema.Draft202012Validator.check_schema(self.output_schema)
        check_schema_complexity(self.output_schema)
        if len(self.required_capabilities) != len(set(self.required_capabilities)):
            raise ValueError("Required capabilities must be unique")
        return self


class TextResponse(StrictModel):
    """Structured inference with separately observed exchange and usage metadata."""

    status: Literal["planned", "complete"]
    backend: dict
    request_sha256: str
    output: dict | None
    execution: dict
    source_content_role: Literal["data"] = "data"
    factual_success: Literal[False] = False


class TextFailure(ToolError):
    """Retain attempted HTTP work after a failed or cancelled submission."""

    backend: dict
    request_sha256: str | None
    execution: dict
