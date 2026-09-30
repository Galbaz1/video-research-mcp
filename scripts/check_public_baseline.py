"""Check published tool contracts, pinned source and protected originals offline."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

BASELINE = "a3d75f6ab87bd893c7d167394fb5bace717f23ec"
SERVERS = {
    "root": ("video_research_mcp", "", 34),
    "explainer": ("video_explainer_mcp", "packages/video-explainer-mcp", 15),
    "agent": ("video_agent_mcp", "packages/video-agent-mcp", 2),
}
LOCKS = ("uv.lock", "packages/video-explainer-mcp/uv.lock", "packages/video-agent-mcp/uv.lock")
CRITERIA_PATHS = (
    "docs/RELEASE_CHECKLIST.md",
    "docs/PUBLISHING.md",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
)
EVIDENCE_PATHS = LOCKS + (
    "pyproject.toml",
    "packages/video-explainer-mcp/pyproject.toml",
    "packages/video-agent-mcp/pyproject.toml",
    "package.json",
    ".claude-plugin/plugin.json",
    "docs/metrics/tool-contract-manifest.json",
    "docs/RELEASE_CHECKLIST.md",
    "docs/PUBLISHING.md",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    "scripts/run_security_smoke.sh",
    "scripts/run_live_tool_security_checks.py",
    "scripts/check_release.py",
    "scripts/smoke_built_mcp.py",
    "src/video_research_mcp/url_policy.py",
    "src/video_research_mcp/local_path_policy.py",
    "src/video_research_mcp/schema_guard.py",
    "src/video_research_mcp/retry.py",
    "src/video_research_mcp/validation.py",
    "src/video_research_mcp/tools/infra.py",
    "src/video_research_mcp/tools/video_cache.py",
    "src/video_research_mcp/tools/video_file.py",
    "src/video_research_mcp/cache.py",
    "src/video_research_mcp/context_cache.py",
    "src/video_research_mcp/tools/youtube_download.py",
    "src/video_research_mcp/tools/content.py",
    "tests/test_url_policy.py",
    "tests/test_video_file.py",
    "tests/test_policy_inheritance.py",
    "tests/test_content_tools.py",
    "tests/test_infra_tools.py",
    "tests/test_research_document_tools.py",
    "tests/test_content_batch_tools.py",
    "tests/installer.test.js",
)
REQUIRED_COMMANDS = (
    (".", "uv sync --locked --extra dev"),
    (".", "uv run --locked pytest tests/ -q"),
    (
        ".",
        "uv run --locked ruff check src/ tests/ scripts/check_release.py scripts/smoke_built_mcp.py",
    ),
    ("packages/video-explainer-mcp", "uv sync --locked --extra dev"),
    ("packages/video-explainer-mcp", "uv run --locked pytest tests/ -q"),
    ("packages/video-explainer-mcp", "uv run --locked ruff check src/ tests/"),
    ("packages/video-agent-mcp", "uv sync --locked --extra dev"),
    ("packages/video-agent-mcp", "uv run --locked pytest tests/ -q"),
    ("packages/video-agent-mcp", "uv run --locked ruff check src/ tests/"),
    (".", "node --test tests/installer.test.js"),
    (".", "./scripts/run_security_smoke.sh"),
    (".", "PYTHONPATH=src uv run --locked python scripts/run_live_tool_security_checks.py"),
    (
        ".",
        "uv run --locked python scripts/export_tool_contract_manifest.py --output /tmp/video-research-tools.json",
    ),
    (".", "uv run --locked python scripts/check_release.py"),
    (".", "npm pack --dry-run"),
    (".", 'release_dir="$(mktemp -d)"'),
    (".", 'uv build --out-dir "$release_dir"'),
    (".", 'uv build --project packages/video-explainer-mcp --out-dir "$release_dir"'),
    (".", 'uv build --project packages/video-agent-mcp --out-dir "$release_dir"'),
    (".", 'npm pack --pack-destination "$release_dir"'),
    (".", 'uvx --from twine twine check "$release_dir"/*.whl "$release_dir"/*.tar.gz'),
    (
        ".",
        'uv run --locked python scripts/smoke_built_mcp.py "$release_dir"/video_research_mcp-*.whl',
    ),
    (".", "uv build"),
    (".", "uv run --locked python scripts/smoke_built_mcp.py dist/*.whl"),
)
FUTURE_DECODE_REQUIREMENT = (
    "Every introduced media decode/crop adapter must preflight source byte ceilings, decoded pixel "
    "counts, valid crop extents and bounded output size/frames/duration before allocation or subprocess work."
)

DISCOVER_CODE = """
import asyncio, importlib, json, sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
package, source = sys.argv[1:]
sys.path.insert(0, source)
importlib.import_module(package + '.dotenv').DEFAULT_ENV_PATH = Path(source) / 'absent.env'
module = importlib.import_module(package + '.server')
assert Path(module.__file__).resolve().is_relative_to(Path(source).resolve())
def convert(value):
    if is_dataclass(value): return asdict(value)
    if hasattr(value, 'model_dump'): return value.model_dump()
    return value
async def run():
    tools = await module.app.list_tools()
    return [{'name': tool.name, 'description': tool.description,
             'annotations': convert(tool.annotations), 'parameters': tool.parameters,
             'output_schema': tool.output_schema} for tool in sorted(tools, key=lambda tool: tool.name)]
print(json.dumps(asyncio.run(run())))
"""


def sha256(path: Path) -> str:
    """Hash exact file bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_text(repo: Path, *args: str) -> str:
    """Read local Git state without remote access."""
    return subprocess.check_output(["git", *args], cwd=repo, text=True).rstrip()


def git_blob(repo: Path, path: str) -> bytes:
    """Read one blob from the exact published source revision."""
    return subprocess.check_output(["git", "show", f"{BASELINE}:{path}"], cwd=repo)


def semantic_schema(schema):
    """Ignore documentation metadata while preserving property names and defaults."""
    if not isinstance(schema, dict):
        return schema
    result = {}
    for key, value in schema.items():
        if key in {"description", "title", "examples"}:
            continue
        if key in {"properties", "$defs", "definitions"}:
            value = {name: semantic_schema(child) for name, child in value.items()}
        elif key in {"anyOf", "oneOf", "allOf", "prefixItems"}:
            value = [semantic_schema(child) for child in value]
        elif key in {"items", "additionalProperties", "not", "if", "then", "else"}:
            value = semantic_schema(value)
        result[key] = value
    return result


def input_issues(old: dict, new: dict) -> list[str]:
    """Allow new optional inputs; preserve existing validation and defaults."""
    old, new = semantic_schema(old), semantic_schema(new)
    issues = []
    old_rest = {key: value for key, value in old.items() if key not in {"properties", "required"}}
    new_rest = {key: value for key, value in new.items() if key not in {"properties", "required"}}
    if old_rest != new_rest:
        issues.append("input structural schema changed")
    if not set(new.get("required", [])) <= set(old.get("required", [])):
        issues.append("new required inputs")
    for name, schema in old.get("properties", {}).items():
        if new.get("properties", {}).get(name) != schema:
            issues.append(f"input removed or changed: {name}")
    return issues


def compatibility_issues(frozen: list[dict], current: list[dict]) -> list[str]:
    """Reject existing contract changes while allowing additional tools."""
    issues = []
    names = [tool["name"] for tool in current]
    if len(names) != len(set(names)):
        issues.append("duplicate current tool")
    mapped = {tool["name"]: tool for tool in current}
    for old in frozen:
        name = old["name"]
        if name not in mapped:
            issues.append(f"tool removed: {name}")
            continue
        new = mapped[name]
        issues.extend(
            f"{name}: {issue}" for issue in input_issues(old["parameters"], new["parameters"])
        )
        if old["annotations"] != new["annotations"]:
            issues.append(f"{name}: annotations changed")
        if semantic_schema(old["output_schema"]) != semantic_schema(new["output_schema"]):
            issues.append(f"{name}: output schema changed")
    return issues


def source_evidence_issues(metadata: dict, repo: Path) -> list[str]:
    """Check the exact frozen source population and its Git blob hashes."""
    evidence = metadata["source_evidence"]
    if set(evidence) != set(EVIDENCE_PATHS):
        return ["baseline source evidence population changed"]
    issues = [
        f"published source hash mismatch: {path}"
        for path, record in evidence.items()
        if hashlib.sha256(git_blob(repo, path)).hexdigest() != record["sha256"]
    ]
    criteria = metadata["full_gate_criteria_sources"]
    if set(criteria) != set(CRITERIA_PATHS):
        issues.append("full gate criteria population changed")
    else:
        issues.extend(
            f"frozen gate criterion text changed: {path}"
            for path, record in criteria.items()
            if record["text"].encode() != git_blob(repo, path)
        )
    return issues


def criteria_issues(metadata: dict) -> list[str]:
    """Reject omitted required gate commands."""
    expected = [{"cwd": cwd, "command": command} for cwd, command in REQUIRED_COMMANDS]
    issues = (
        []
        if metadata["required_commands"] == expected
        else ["required gate command population changed"]
    )
    if metadata.get("future_decode_requirement") != FUTURE_DECODE_REQUIREMENT:
        issues.append("future decode/crop bounds requirement changed")
    return issues


def protection_issues(protection: dict) -> list[str]:
    """Verify protected originals plus the original branch, HEAD and dirty scope."""
    issues = []
    records = [protection["manifest"], *protection["files"]]
    for record in records:
        path = Path(record["path"])
        if not path.is_file() or sha256(path) != record["sha256"]:
            issues.append(f"protected original missing or changed: {path}")
    original = protection["checkout"]
    repo = Path(original["path"])
    if git_text(repo, "rev-parse", "HEAD") != original["head"]:
        issues.append("original HEAD changed")
    if git_text(repo, "branch", "--show-current") != original["branch"]:
        issues.append("original branch changed")
    status = git_text(repo, "status", "--porcelain")
    dirty = sorted(line[3:] for line in status.splitlines() if line)
    if dirty != sorted(original["dirty_files"]):
        issues.append("original dirty-file scope changed")
    return issues


def discover(repo: Path, source_tree: Path, package: str, scope: str) -> list[dict]:
    """List source-tree registrations in the existing package environment only."""
    python = repo / scope / ".venv/bin/python"
    if not python.is_file():
        raise ValueError(f"existing locked environment missing: {scope or 'root'}")
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "GEMINI_API_KEY": "test-key-not-real",
        "GEMINI_TRACING_ENABLED": "false",
        "WEAVIATE_URL": "",
        "WEAVIATE_API_KEY": "",
    }
    result = subprocess.run(
        [str(python), "-c", DISCOVER_CODE, package, str(source_tree / scope / "src")],
        cwd=source_tree,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def discover_all(repo: Path, source_tree: Path) -> dict:
    """Inspect three independent source registries without tool execution."""
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = {
            name: pool.submit(discover, repo, source_tree, package, scope)
            for name, (package, scope, _) in SERVERS.items()
        }
        return {
            name: {"tool_count": len(job.result()), "tools": job.result()}
            for name, job in jobs.items()
        }


def published_discovery(repo: Path) -> dict:
    """Import exact published source from a temporary local Git archive."""
    paths = [str(Path(scope) / "src") for _, scope, _ in SERVERS.values()]
    data = subprocess.check_output(["git", "archive", BASELINE, *paths], cwd=repo)
    with tempfile.TemporaryDirectory(prefix="vrm-public-baseline-") as scratch:
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            archive.extractall(scratch, filter="data")
        return discover_all(repo, Path(scratch))


def validate(repo: Path) -> dict:
    """Validate the frozen baseline and report current source discovery separately."""
    metrics = repo / "docs/metrics"
    metadata = json.loads((metrics / "public-baseline.json").read_text())
    contracts_path = metrics / "public-baseline-tool-contracts.json"
    contracts = json.loads(contracts_path.read_text())
    issues = (
        source_evidence_issues(metadata, repo)
        + criteria_issues(metadata)
        + protection_issues(metadata["protected_originals"])
    )
    if metadata["source_revision"] != BASELINE or contracts["source_revision"] != BASELINE:
        issues.append("published baseline revision changed")
    if sha256(contracts_path) != metadata["tool_contracts_sha256"]:
        issues.append("frozen tool-contract file hash mismatch")
    published = published_discovery(repo)
    if contracts["servers"] != published:
        issues.append("frozen contracts differ from actual published source discovery")
    recorded_root = json.loads(git_blob(repo, "docs/metrics/tool-contract-manifest.json"))
    if recorded_root["tools"] != published["root"]["tools"]:
        issues.append("published root manifest differs from source discovery")
    current = discover_all(repo, repo)
    for name, (_, _, count) in SERVERS.items():
        if published[name]["tool_count"] != count:
            issues.append(f"published {name} tool population changed")
        issues.extend(
            f"{name}: {issue}"
            for issue in compatibility_issues(published[name]["tools"], current[name]["tools"])
        )
    return {
        "source_revision": BASELINE,
        "current_source_revision": git_text(repo, "rev-parse", "HEAD"),
        "published_tool_counts": {name: server["tool_count"] for name, server in published.items()},
        "current_source_tool_counts": {
            name: server["tool_count"] for name, server in current.items()
        },
        "current_lock_sha256": {path: sha256(repo / path) for path in LOCKS},
        "installed_user_client": "not inspected",
        "required_gate_commands": "frozen requirements; not executed by this check",
        "provider_calls": 0,
        "issues": issues,
    }


def main() -> int:
    """Run read-only baseline checks with a nonzero exit on incompatibility."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = validate(Path(__file__).resolve().parents[1])
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"FAIL: public baseline check could not complete: {error}")
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("FAIL" if result["issues"] else "PASS", json.dumps(result))
    return bool(result["issues"])


if __name__ == "__main__":
    raise SystemExit(main())
