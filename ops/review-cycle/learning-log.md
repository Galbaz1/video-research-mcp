# Review Cycle Learning Log

## Iteration 1 (Architecture and Trust Boundaries) - 2026-03-01T03:26:51Z
- Observation: `content_analyze` accepted arbitrary URLs and passed them directly into Gemini `UrlContext` without applying the repo's SSRF policy gate.
- Inference: Trust boundary handling was inconsistent; URL hardening existed for document downloads (`url_policy.py`) but not for URL-context analysis.
- Strategy: Reuse `validate_url()` at tool ingress to unify outbound URL controls across tooling.
- Validation: Added guard in `content_analyze` and a regression test to assert non-HTTPS URLs are rejected pre-model-call.
- Confidence change: 0.55 -> 0.80 for URL-boundary consistency in content tooling after patch + test.
- Delivery confidence: 0.80 -> 0.88 after PR #30 merged cleanly into `codex/review-mainline`.

## Iteration 2 seed hypotheses
- Add an explicit per-tool trust policy matrix (local file, remote URL, external API) and test each edge.
- Evaluate whether `infra_*` mutating tools need an opt-in guard for non-local transports.

## Iteration 2 (Validation and Schema Contracts) - 2026-03-15T03:45:00Z
- Observation: list-typed tool params could degrade into raw strings and be processed as iterables, creating ambiguous behavior and possible resource fanout.
- Inference: boundary coercion was permissive by default and lacked strict post-coercion type enforcement.
- Strategy: create a shared strict validator (`coerce_string_list_param`) and apply at ingress for all reviewed list parameters.
- Validation: added regression tests for malformed string inputs and updated URL redirect handling tests; `ruff check` passes and `tests/test_url_policy.py` passes.
- Confidence change: 0.61 -> 0.86 for schema/validation contract reliability in reviewed surfaces.
