#!/usr/bin/env python3
"""Run live security checks against MCP tool entrypoints.

This script calls tool functions directly (same entrypoints used by MCP) and
prints PASS/FAIL expectations for high-impact security controls.

Use `--run-online` to include one real Gemini-backed check.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import video_research_mcp.config as cfg_mod
from video_research_mcp.tools import content as content_mod
from video_research_mcp.tools import infra as infra_mod
from video_research_mcp.tools import research_document as research_doc_mod


def _unwrap_tool(tool):
    """Return callable coroutine whether wrapped by FastMCP or not."""
    return getattr(tool, "fn", tool)


CONTENT_ANALYZE = _unwrap_tool(content_mod.content_analyze)
CONTENT_EXTRACT = _unwrap_tool(content_mod.content_extract)
INFRA_CONFIGURE = _unwrap_tool(infra_mod.infra_configure)
RESEARCH_DOCUMENT = _unwrap_tool(research_doc_mod.research_document)


@contextmanager
def _with_env(updates: dict[str, str | None]) -> Iterator[None]:
    """Temporarily patch environment and reset config singleton."""
    previous = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        cfg_mod._config = None
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        cfg_mod._config = None


@dataclass
class CheckResult:
    """Result of a single live security check."""

    name: str
    status: str  # PASS | FAIL | SKIP
    expectation: str
    observed: str


def _as_error(result: dict) -> str:
    """Format tool error result for compact output."""
    category = result.get("category", "<missing>")
    message = result.get("error", "<missing>")
    return f"{category}: {message}"


async def _check_non_https_url_blocked() -> CheckResult:
    """Ensure URL policy blocks non-HTTPS content ingestion."""
    expectation = "category=URL_POLICY_BLOCKED"
    with _with_env({"GEMINI_API_KEY": "test-key-not-real"}):
        result = await CONTENT_ANALYZE(url="http://example.com")
    if isinstance(result, dict) and result.get("category") == "URL_POLICY_BLOCKED":
        return CheckResult("non_https_url_blocked", "PASS", expectation, _as_error(result))
    return CheckResult("non_https_url_blocked", "FAIL", expectation, str(result))


async def _check_local_path_boundary() -> CheckResult:
    """Ensure local file boundary policy rejects out-of-root file access."""
    expectation = "category=PERMISSION_DENIED"
    with tempfile.TemporaryDirectory(prefix="live_root_") as root_dir, tempfile.TemporaryDirectory(
        prefix="live_outside_"
    ) as outside_dir:
        outside_file = Path(outside_dir) / "outside.txt"
        outside_file.write_text("outside boundary", encoding="utf-8")
        with _with_env(
            {
                "GEMINI_API_KEY": "test-key-not-real",
                "LOCAL_FILE_ACCESS_ROOT": root_dir,
            }
        ):
            result = await CONTENT_ANALYZE(file_path=str(outside_file))
    if isinstance(result, dict) and result.get("category") == "PERMISSION_DENIED":
        return CheckResult("local_path_boundary", "PASS", expectation, _as_error(result))
    return CheckResult("local_path_boundary", "FAIL", expectation, str(result))


async def _check_infra_mutation_gate_disabled() -> CheckResult:
    """Ensure infra mutation is denied when policy toggle is disabled."""
    expectation = "category=PERMISSION_DENIED"
    with _with_env({"INFRA_MUTATIONS_ENABLED": "false", "INFRA_ADMIN_TOKEN": None}):
        result = await INFRA_CONFIGURE(model="gemini-3-flash-preview")
    if isinstance(result, dict) and result.get("category") == "PERMISSION_DENIED":
        return CheckResult("infra_mutation_gate_disabled", "PASS", expectation, _as_error(result))
    return CheckResult("infra_mutation_gate_disabled", "FAIL", expectation, str(result))


async def _check_infra_token_gate() -> CheckResult:
    """Ensure infra mutation token policy denies bad token and accepts valid token."""
    expectation = "wrong token denied + valid token accepted"
    with _with_env({"INFRA_MUTATIONS_ENABLED": "true", "INFRA_ADMIN_TOKEN": "live-check-token"}):
        denied = await INFRA_CONFIGURE(model="gemini-3-flash-preview", auth_token="wrong")
        allowed = await INFRA_CONFIGURE(
            model="gemini-3-flash-preview",
            auth_token="live-check-token",
        )
    denied_ok = isinstance(denied, dict) and denied.get("category") == "PERMISSION_DENIED"
    allowed_ok = isinstance(allowed, dict) and "error" not in allowed
    if isinstance(allowed, dict) and "error" not in allowed:
        current_model = allowed.get("current_config", {}).get("default_model", "<missing>")
        allowed_observed = f"success default_model={current_model}"
    else:
        allowed_observed = str(allowed)
    observed = (
        f"denied={_as_error(denied) if isinstance(denied, dict) else denied}; "
        f"allowed={allowed_observed}"
    )
    if denied_ok and allowed_ok:
        return CheckResult("infra_token_gate", "PASS", expectation, observed)
    return CheckResult("infra_token_gate", "FAIL", expectation, observed)


async def _check_research_source_limit() -> CheckResult:
    """Ensure research_document enforces configured source limits."""
    expectation = "tool error includes 'Too many document sources requested'"
    with _with_env(
        {
            "GEMINI_API_KEY": "test-key-not-real",
            "RESEARCH_DOCUMENT_MAX_SOURCES": "1",
        }
    ):
        result = await RESEARCH_DOCUMENT(
            instruction="Limit test",
            file_paths=["/tmp/doc-a.pdf", "/tmp/doc-b.pdf"],
        )
    if isinstance(result, dict) and "Too many document sources requested" in result.get("error", ""):
        return CheckResult("research_source_limit", "PASS", expectation, _as_error(result))
    return CheckResult("research_source_limit", "FAIL", expectation, str(result))


async def _check_online_extract() -> CheckResult:
    """Run one online Gemini-backed extraction check when requested."""
    expectation = "successful extraction with non-empty summary"
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return CheckResult(
            "online_extract",
            "SKIP",
            expectation,
            "GEMINI_API_KEY not set in current shell",
        )
    schema = {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
        "additionalProperties": False,
    }
    with _with_env({"GEMINI_API_KEY": api_key}):
        result = await CONTENT_EXTRACT(
            content="Codex can run recurring security checks for MCP servers.",
            schema=schema,
        )
    summary = result.get("summary") if isinstance(result, dict) else None
    if isinstance(summary, str) and summary.strip():
        return CheckResult("online_extract", "PASS", expectation, str(result))
    return CheckResult("online_extract", "FAIL", expectation, str(result))


def _print_results(results: list[CheckResult]) -> None:
    """Print a compact status report."""
    print("\nLive MCP Tool Security Checks")
    print("=" * 32)
    for item in results:
        print(f"[{item.status}] {item.name}")
        print(f"  expect: {item.expectation}")
        print(f"  got:    {item.observed}")
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    skipped = sum(1 for r in results if r.status == "SKIP")
    print("\nSummary")
    print(f"  pass={passed} fail={failed} skip={skipped}")


async def _run(run_online: bool) -> int:
    """Execute selected checks and return process exit code."""
    checks = [
        _check_non_https_url_blocked,
        _check_local_path_boundary,
        _check_infra_mutation_gate_disabled,
        _check_infra_token_gate,
        _check_research_source_limit,
    ]
    if run_online:
        checks.append(_check_online_extract)

    results: list[CheckResult] = []
    for check in checks:
        try:
            results.append(await check())
        except Exception as exc:  # pragma: no cover - defensive for live script
            results.append(
                CheckResult(
                    name=check.__name__,
                    status="FAIL",
                    expectation="check executes without unhandled exception",
                    observed=f"{type(exc).__name__}: {exc}",
                )
            )

    _print_results(results)
    return 1 if any(r.status == "FAIL" for r in results) else 0


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-online",
        action="store_true",
        help="Run one Gemini-backed live extraction check (requires GEMINI_API_KEY).",
    )
    args = parser.parse_args()
    return asyncio.run(_run(run_online=args.run_online))


if __name__ == "__main__":
    raise SystemExit(main())
