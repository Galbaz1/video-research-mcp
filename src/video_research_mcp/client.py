"""Shared Gemini client singleton with thinking-level support."""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, TypeAdapter

if TYPE_CHECKING:
    from google import genai
    from google.genai import types

from .config import VALID_THINKING_LEVELS, get_config
from .retry import with_retry

logger = logging.getLogger(__name__)


def _resolve_thinking_level(value: str) -> str:
    """Normalize and validate a thinking level string.

    Raises:
        ValueError: If the level is not in VALID_THINKING_LEVELS.
    """
    level = value.strip().lower()
    if level not in VALID_THINKING_LEVELS:
        allowed = ", ".join(sorted(VALID_THINKING_LEVELS))
        raise ValueError(f"Invalid thinking level '{value}'. Allowed: {allowed}")
    return level


class GeminiClient:
    """Process-wide Gemini client pool (one client per API key)."""

    _clients: dict[str, genai.Client] = {}

    @classmethod
    def get(cls, api_key: str | None = None) -> genai.Client:
        """Return (or create) the shared client for *api_key*."""
        from google import genai  # lazy — saves ~280ms at startup

        key = api_key or get_config().gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        if not key:
            raise ValueError("No Gemini API key — set GEMINI_API_KEY or pass api_key explicitly")
        if key not in cls._clients:
            cls._clients[key] = genai.Client(api_key=key)
            logger.info("Created Gemini client (key …%s)", key[-4:])
        return cls._clients[key]

    @classmethod
    async def generate(
        cls,
        contents: Any,
        *,
        model: str | None = None,
        thinking_level: str | None = None,
        response_schema: dict | None = None,
        temperature: float | None = None,
        system_instruction: str | None = None,
        tools: list[types.Tool] | None = None,
        **kwargs: Any,
    ) -> str:
        """Generate text via Gemini with thinking support and optional structured output.

        Builds a GenerateContentConfig from resolved model/thinking/temperature
        defaults, delegates to the async API with retry, and strips thinking
        parts from the response.

        Args:
            contents: Prompt contents (text, multimodal parts, or conversation history).
            model: Override model ID (defaults to config's default_model).
            thinking_level: Override thinking level (defaults to config's default).
            response_schema: JSON schema dict to constrain output format.
            temperature: Override temperature (defaults to config's default).
            system_instruction: System-level instruction prepended to the prompt.
            tools: Gemini tool wiring (e.g. GoogleSearch, UrlContext).
            **kwargs: Forwarded to the underlying generate_content call.

        Returns:
            The model's text response with thinking parts stripped.
        """
        from google.genai import types  # lazy — saves ~160ms at startup

        cfg = get_config()
        resolved_model = model or cfg.default_model
        resolved_thinking = _resolve_thinking_level(thinking_level or cfg.default_thinking_level)

        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level=resolved_thinking),
            temperature=temperature if temperature is not None else cfg.default_temperature,
        )
        if system_instruction:
            config.system_instruction = system_instruction
        if response_schema:
            config.response_mime_type = "application/json"
            config.response_json_schema = response_schema
        if tools:
            config.tools = tools

        client = cls.get()
        response = await with_retry(
            lambda: client.aio.models.generate_content(
                model=resolved_model,
                contents=contents,
                config=config,
                **kwargs,
            )
        )

        # Strip thinking parts — only return user-visible text
        parts = response.candidates[0].content.parts if response.candidates else []
        text_parts = [p.text for p in parts if p.text and not getattr(p, "thought", False)]
        return "\n".join(text_parts) if text_parts else (response.text or "")

    @classmethod
    async def generate_structured(
        cls,
        contents: Any,
        *,
        schema: type[BaseModel],
        model: str | None = None,
        thinking_level: str | None = None,
        system_instruction: str | None = None,
        tools: list[types.Tool] | None = None,
        **kwargs: Any,
    ) -> BaseModel:
        """Generate and validate into a Pydantic model via response_json_schema.

        Delegates to ``generate()`` with the model's JSON schema, then
        deserialises the response text into a validated Pydantic instance.

        Args:
            contents: Prompt contents (text, multimodal, or history).
            schema: Pydantic model class defining the expected output shape.
            model: Override model ID.
            thinking_level: Override thinking level.
            system_instruction: System-level instruction for the model.
            tools: Gemini tool wiring (e.g. GoogleSearch, UrlContext).
            **kwargs: Forwarded to ``generate()``.

        Returns:
            Validated Pydantic model instance.
        """
        raw = await cls.generate(
            contents,
            model=model,
            thinking_level=thinking_level,
            system_instruction=system_instruction,
            tools=tools,
            response_schema=schema.model_json_schema(),
            **kwargs,
        )
        return schema.model_validate_json(raw)

    @classmethod
    async def generate_json_validated(
        cls,
        contents: Any,
        *,
        schema: type[BaseModel] | dict,
        model: str | None = None,
        thinking_level: str | None = None,
        system_instruction: str | None = None,
        strict: bool = False,
        **kwargs: Any,
    ) -> dict:
        """Generate JSON and validate against a Pydantic model or JSON Schema dict.

        Dual-path validation:
        - Pydantic model: uses TypeAdapter for zero-dependency validation.
        - dict (JSON Schema): lazy-imports jsonschema; skips on ImportError.

        Args:
            contents: Prompt contents.
            schema: Pydantic model class or JSON Schema dict.
            model: Override model ID.
            thinking_level: Override thinking level.
            system_instruction: System instruction.
            strict: True = raise on failure; False = log warning, return unvalidated.
            **kwargs: Forwarded to generate().

        Returns:
            Parsed and optionally validated dict.

        Raises:
            ValueError: If strict=True and validation fails.
        """
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            response_schema = schema.model_json_schema()
        else:
            response_schema = schema

        raw = await cls.generate(
            contents,
            model=model,
            thinking_level=thinking_level,
            system_instruction=system_instruction,
            response_schema=response_schema,
            **kwargs,
        )

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            if strict:
                raise ValueError(f"Gemini returned non-JSON: {raw[:200]!r}") from exc
            logger.warning("generate_json_validated: non-JSON response, returning raw")
            return {"raw": raw}

        # Pydantic path: validate and return coerced output
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            try:
                validated = TypeAdapter(schema).validate_python(parsed)
                return validated.model_dump() if hasattr(validated, "model_dump") else parsed
            except Exception as exc:
                if strict:
                    raise ValueError(f"Schema validation failed: {exc}") from exc
                logger.warning("generate_json_validated: validation failed: %s", exc)
                return parsed

        # Dict (JSON Schema) path: validate in-place, return parsed
        try:
            import jsonschema
            jsonschema.validate(parsed, schema)
        except ImportError:
            if strict:
                raise ValueError(
                    "jsonschema package required for strict dict schema validation"
                )
            logger.debug("jsonschema not installed, skipping dict schema validation")
        except Exception as exc:
            if strict:
                raise ValueError(f"Schema validation failed: {exc}") from exc
            logger.warning("generate_json_validated: validation failed: %s", exc)

        return parsed

    @classmethod
    async def close_all(cls) -> int:
        """Shut down all shared clients. Returns count closed."""
        count = 0
        for key, client in list(cls._clients.items()):
            try:
                await client.aio.close()
            except Exception:
                pass
            try:
                client.close()
            except Exception:
                pass
            count += 1
        cls._clients.clear()
        logger.info("Closed %d Gemini client(s)", count)
        return count
