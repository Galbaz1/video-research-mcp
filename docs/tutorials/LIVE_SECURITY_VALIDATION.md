# Live Security Validation Runbook

Use this runbook after security changes merge, before release, and during periodic health checks.

## What Codex Can Do For You
- Keep CI checks wired (`lint`, `test`, `security-smoke`) and update coverage as mitigations evolve.
- Maintain reusable scripts:
  - [`scripts/run_security_smoke.sh`](../../scripts/run_security_smoke.sh)
  - [`scripts/run_live_tool_security_checks.py`](../../scripts/run_live_tool_security_checks.py)
- Open PRs for remediation and provide exact pass/fail output.

## What You Need To Do
- Enable required status checks in GitHub branch protection.
- Run live checks with real credentials/staging config.
- Confirm behavior in your MCP client for both blocked and allowed paths.

## When To Run
1. Immediately after security-related PRs merge.
2. Before any release.
3. Weekly (or nightly) as an operational safety check.
4. Whenever URL/path/download/prompt/infra policy code changes.

## Step 1: Enable Required Checks (One-Time)
1. GitHub -> `Settings` -> `Branches` -> add/update protection rule for `main`.
2. Enable `Require status checks to pass before merging`.
3. Mark these checks as required:
- `lint`
- `test (3.11)`
- `test (3.12)`
- `test (3.13)`
- `security-smoke`
4. Repeat for `codex/review-mainline` if you continue using it as the security integration branch.

## Step 2: Run Fast Security Smoke (No API Spend)
```bash
./scripts/run_security_smoke.sh
```

Expected:
- 8 tests run and pass.
- No external API calls required.

## Step 3: Run Live Tool Security Checks
Offline policy checks (no Gemini call):
```bash
PYTHONPATH=src uv run python scripts/run_live_tool_security_checks.py
```

Expected PASS checks:
- `non_https_url_blocked`
- `local_path_boundary`
- `infra_mutation_gate_disabled`
- `infra_token_gate`
- `research_source_limit`

Online check with real Gemini call:
```bash
GEMINI_API_KEY=... PYTHONPATH=src uv run python scripts/run_live_tool_security_checks.py --run-online
```

Expected additional PASS check:
- `online_extract`

If `online_extract` is `SKIP`, either:
- `GEMINI_API_KEY` was not set in your shell, or
- the provider returned a transient availability/capacity error (e.g. temporary 503/high demand).

To treat transient upstream errors as release-blocking failures:
```bash
GEMINI_API_KEY=... PYTHONPATH=src uv run python scripts/run_live_tool_security_checks.py --run-online --strict-online
```

## Step 4: MCP Client Live Validation (Manual)
Run these in your MCP client against a staging server:
1. Non-HTTPS URL should be rejected:
- `content_analyze(url="http://example.com")`
2. Path outside boundary should be rejected:
- start server with `LOCAL_FILE_ACCESS_ROOT` set, then call `content_analyze(file_path=...)` with an out-of-root path.
3. Infra mutation should be blocked when disabled:
- `infra_configure(model="...")` with `INFRA_MUTATIONS_ENABLED=false`.
4. Infra mutation should require token when configured:
- `INFRA_MUTATIONS_ENABLED=true` + `INFRA_ADMIN_TOKEN=...`, then test wrong and correct token.
5. Source-count limit should be enforced:
- set `RESEARCH_DOCUMENT_MAX_SOURCES=1`, then call `research_document(...)` with 2+ sources.

## Step 5: Release-Time Checklist
Before tagging a release:
1. Run Step 2 and Step 3.
2. Attach output snippets to the release PR.
3. If Step 2 fails, block release and open a remediation PR.
4. In Step 3, block release on policy check FAILs. For `online_extract`, retry once with `GEMINI_MODEL=gemini-3-flash-preview`; if still `SKIP` due transient provider availability, log it in the PR and continue.
