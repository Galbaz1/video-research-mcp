---
paths: "src/**/*.py"
---

# Google GenAI SDK Patterns (>=1.57)

## Client

- Singleton via `GeminiClient.get()` — never construct `genai.Client()` directly
- All generation through `GeminiClient.generate()`, `.generate_structured()`, or `.generate_json_validated()`
- Async API: `client.aio.models.generate_content()`

## Types

- Import from `google.genai import types`
- Key types: `types.Part`, `types.Content`, `types.GenerateContentConfig`, `types.ThinkingConfig`
- Build video parts: `types.Part.from_uri(file_uri=..., mime_type=...)`

## Thinking

- All calls include `ThinkingConfig(thinking_level=...)` via config
- Levels: "minimal", "low", "medium", "high"
- Strip thinking parts from responses: `getattr(p, "thought", False)` — this is intentional defensive code, not a compat shim

## Context Caching

- `cached_content` in `GenerateContentConfig` — cache name string
- Registry maps `(content_id, model)` → cache name
- Cache prewarm via `context_cache.start_prewarm()`, session lookup via `ensure_session_cache()` (which uses `lookup_or_await()` internally)
- Caches expire via TTL (default 1 hour) — no manual cleanup needed on shutdown

## Validation

- `generate_json_validated()` — dual-path validation (Pydantic TypeAdapter / jsonschema)
- Accepts `schema: type[BaseModel] | dict` — Pydantic model or JSON Schema dict
- `strict=True` raises on failure; `strict=False` logs warning and returns unvalidated
- jsonschema is a lazy import — skips validation when not installed

## Models

- Default: `gemini-3.6-flash` (config.py) — both `default_model` and `flash_model` point here; thinking_level is the dial
- Gemini 3.6 Flash does not accept `temperature`, `top_p`, or `top_k`; omit sampling parameters for this model
- Opt-in alternates via `infra_configure(preset="best"|"stable"|"budget")` for Pro 3.1, the 3.6 Flash standard, or 3.5 Flash-Lite
