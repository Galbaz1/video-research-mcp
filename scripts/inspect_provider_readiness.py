#!/usr/bin/env python3
"""Inspect provider/runtime presence without requests, client imports or mutations."""

from __future__ import annotations

import argparse
import ast
import hashlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import re
import shutil

from video_research_mcp.dotenv import DEFAULT_ENV_PATH, _is_unset_or_placeholder, parse_dotenv

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "docs/integrations/provider-readiness.json"
DEV_INPUTS = "tests/evaluation/fixtures/inputs.json"
CONFIG_SOURCES = {
    "src/video_research_mcp/config.py",
    "packages/video-explainer-mcp/src/video_explainer_mcp/config.py",
    "packages/video-agent-mcp/src/video_agent_mcp/config.py",
}
SOURCE_CONTRACTS = {
    "src/video_research_mcp/dotenv.py",
    "src/video_research_mcp/weaviate_client.py",
    "src/video_research_mcp/weaviate_migrate.py",
    "src/video_research_mcp/academic_client.py",
    "src/video_research_mcp/client.py",
    "src/video_research_mcp/image_ops.py",
    "src/video_research_mcp/tools/research_web.py",
    "packages/video-explainer-mcp/src/video_explainer_mcp/prereqs.py",
    "packages/video-agent-mcp/src/video_agent_mcp/sdk_runner.py",
}
PRIVATE_DEV_ROOT = (
    Path.home()
    / ".local/state/video-research-mcp/capability-programme/2026-09-30/provider-readiness/dev-fixtures"
)


def digest(path: Path) -> str:
    """Hash a declared source or development artifact without exposing its body."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def effective_environment(env: dict, env_file: Path) -> dict:
    """Mirror shared dotenv precedence in a private dictionary, without injection."""
    result = dict(env)
    for key, value in parse_dotenv(env_file).items():
        if _is_unset_or_placeholder(key, result.get(key)):
            result[key] = value
    return result


def present(env: dict, key: str) -> bool:
    """Report non-placeholder presence while retaining no credential value."""
    value = env.get(key, "").strip()
    return bool(value) and not _is_unset_or_placeholder(key, value) and not value.startswith("${")


def literal_default(node: ast.AST):
    """Resolve the literals and byte-size multiplication used by current config."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return literal_default(node.left) * literal_default(node.right)
    return None


def config_defaults(path: Path) -> dict:
    """Read literal Field defaults without importing clients or executing factories."""
    tree = ast.parse(path.read_text())
    config = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ServerConfig")
    result = {}
    for node in config.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Call):
            for keyword in node.value.keywords:
                if keyword.arg == "default":
                    result[node.target.id] = literal_default(keyword.value)
    return result


def package_presence(names: list[str]) -> dict:
    """Read installed distribution metadata without importing provider modules."""
    result = {}
    for name in names:
        try:
            version = metadata.version(name)
        except metadata.PackageNotFoundError:
            version = None
        result[name] = {
            "installed": version is not None,
            "version": version
            if version and re.fullmatch(r"[0-9][A-Za-z0-9.+-]{0,60}", version)
            else None,
        }
    return result


def enabled(kind: str, env: dict) -> bool:
    """Resolve current source enable conditions without touching service endpoints."""
    if kind == "planned":
        return False
    if kind == "weaviate":
        return present(env, "WEAVIATE_URL")
    if kind == "reranker":
        flag = env.get("RERANKER_ENABLED", "").lower()
        return present(env, "WEAVIATE_URL") and (
            flag == "true" or (present(env, "COHERE_API_KEY") and flag != "false")
        )
    if kind == "tracing":
        return (
            present(env, "MLFLOW_TRACKING_URI")
            and env.get("GEMINI_TRACING_ENABLED", "").lower() != "false"
        )
    if kind == "explainer":
        return present(env, "EXPLAINER_PATH")
    return True


def config_observation(root: Path, row: dict, env: dict) -> dict:
    """Tie settings to current config fields and reveal only safe numeric values."""
    if not row["config_source"]:
        return {}
    path = root / row["config_source"]
    defaults = config_defaults(path)
    source = path.read_text()
    result = {}
    for field, key in row["config_bindings"].items():
        if field not in defaults or key not in source:
            raise ValueError("Declared setting differs from current config contract")
        observation = {
            "field": field,
            "environment_variable": key,
            "override_present": present(env, key),
            "resolved_from": "environment-or-shared-dotenv"
            if present(env, key)
            else "current-source-default",
            "value": "redacted",
        }
        if type(defaults[field]) is int:
            try:
                value = int(env.get(key, str(defaults[field])))
                observation["value"] = value if value > 0 else "invalid"
            except ValueError:
                observation["value"] = "invalid"
        result[field] = observation
    return result


def companion_observation(root: Path, row: dict, env: dict, missing: list) -> tuple[str, dict]:
    """Inspect TTS selection and renderer auto-detection without execution."""
    if row["enable"] == "tts":
        default = config_defaults(root / row["config_source"])["tts_provider"]
        provider = env.get("EXPLAINER_TTS_PROVIDER", default).strip().lower()
        details = {
            "provider": provider if provider in {"mock", "elevenlabs", "edge"} else "invalid"
        }
        if provider == "mock":
            return "mocked", details
        if (
            provider not in {"elevenlabs", "edge"}
            or missing
            or provider == "elevenlabs"
            and not present(env, "ELEVENLABS_API_KEY")
        ):
            return "missing", details
        return "configured-but-unverified", details
    path = (
        Path(env["EXPLAINER_PATH"]).expanduser()
        if present(env, "EXPLAINER_PATH")
        else root / "packages/video-explainer"
    )
    if not present(env, "EXPLAINER_PATH") and not (path / "pyproject.toml").is_file():
        return "disabled", {}
    details = {
        "checkout_exists": path.is_dir(),
        "console_script_exists": (path / ".venv/bin/video-explainer").is_file(),
        "remotion_dependencies_exist": (path / "remotion/node_modules/@remotion").is_dir(),
        "python_present": bool(shutil.which(env.get("EXPLAINER_PYTHON", "python3"))),
    }
    status = "missing" if missing or not all(details.values()) else "configured-but-unverified"
    details["path_selection"] = (
        "configured" if present(env, "EXPLAINER_PATH") else "current-source-auto-detection"
    )
    details["license_clearance"] = "blocked-until-selected-runtime-receipt"
    return status, details


def inspect_integration(root: Path, row: dict, env: dict) -> dict:
    """Keep installed/configured/mock observations distinct from live acceptance."""
    packages = package_presence(row["packages"])
    executables = {name: bool(shutil.which(name)) for name in row["executables"]}
    keys = set(row["credential_any"] + row.get("credential_optional", []))
    keys.update(key for field, key in row["config_bindings"].items() if "api_key" in field)
    credentials = {key: present(env, key) for key in sorted(keys)}
    missing = [name for name, value in packages.items() if not value["installed"]]
    missing += [name for name, value in executables.items() if not value]
    configured = any(credentials.values()) or row["enable"] in {
        "weaviate",
        "reranker",
        "tracing",
        "explainer",
    }
    if row["credential_any"] and not any(credentials[k] for k in row["credential_any"]):
        missing.append("credential-or-separately-verified-login")
    status = "missing" if missing else "configured-but-unverified" if configured else "installed"
    details = {}
    if row["enable"] in {"tts", "explainer"}:
        status, details = companion_observation(root, row, env, missing)
    elif not enabled(row["enable"], env):
        status = "disabled"
    if row["id"] == "weaviate-vectorizer":
        selected = env.get("WEAVIATE_VECTORIZER", "").strip().lower() or (
            "openai" if present(env, "OPENAI_API_KEY") else "weaviate"
        )
        details["vectorizer"] = (
            selected if selected in {"openai", "weaviate", "ollama"} else "invalid"
        )
        if enabled("weaviate", env) and (
            selected not in {"openai", "weaviate", "ollama"}
            or selected == "openai"
            and not present(env, "OPENAI_API_KEY")
        ):
            status = "missing"
    return {
        "id": row["id"],
        "adopted": row["adopted"],
        "state": status,
        "packages": packages,
        "executables_present": executables,
        "credential_presence": credentials,
        "config_observation": config_observation(root, row, env),
        "details": details,
        "usage_visibility": row["usage_visibility"],
        "live_verified": False,
        "run_authority": "not-granted",
    }


def validate_run_bounds(plan: dict, ceiling: float) -> None:
    """Keep every proposed spend, operation and time limit finite and positive."""
    amount = plan["allocated_spend_ceiling_usd"]
    if not math.isfinite(amount) or not 0 < amount <= ceiling:
        raise ValueError("Run plan has an invalid spend bound")
    fields = (
        "logical_calls_max",
        "generation_or_synthesis_attempts_max",
        "provider_http_operations_max",
        "wall_time_seconds_max",
    )
    if any(type(plan[field]) is not int or plan[field] < 1 for field in fields):
        raise ValueError("Run plan has an invalid attempt, operation or time bound")
    if (
        plan["generation_or_synthesis_attempts_max"] != plan["logical_calls_max"]
        or plan["provider_http_operations_max"] < plan["logical_calls_max"]
    ):
        raise ValueError("Run plan hides generation attempts or provider operations")


def validate_development_sources(root: Path, fixtures: list) -> None:
    """Hash only declared development cases and sources, preserving the heldout embargo."""
    inputs = root / DEV_INPUTS
    cases = {case["id"]: case for case in json.loads(inputs.read_text())}
    for fixture in fixtures:
        if "input_manifest" in fixture:
            if fixture["input_manifest"] != DEV_INPUTS:
                raise ValueError("Unexpected development input manifest")
            case = json.dumps(cases[fixture["case_id"]], sort_keys=True, separators=(",", ":"))
            if (
                digest(inputs) != fixture["input_manifest_sha256"]
                or hashlib.sha256(case.encode()).hexdigest() != fixture["case_sha256"]
            ):
                raise ValueError("Declared development case or input manifest hash drift")
        for source in fixture.get("source_receipts", [fixture]):
            path = Path(source["path"])
            path = path if path.is_absolute() else root / path
            allowed = path.resolve().is_relative_to(
                (root / "tests/evaluation/fixtures/sources").resolve()
            ) or path.resolve().is_relative_to(PRIVATE_DEV_ROOT.resolve())
            if not allowed or "heldout" in str(path.resolve()).lower():
                raise ValueError(
                    "Readiness inspection must only consume declared development sources"
                )
            if digest(path) != source["sha256"]:
                raise ValueError("Declared development artifact hash drift")


def validate_plans(root: Path, manifest: dict) -> None:
    """Reject unbounded drafts and drift in declared development source artifacts."""
    proposal = manifest["live_run_proposal"]
    plans = proposal["plans"]
    if (
        set(manifest["config_sources"].values()) != CONFIG_SOURCES
        or set(manifest["additional_source_contracts"]) != SOURCE_CONTRACTS
    ):
        raise ValueError("Unexpected source contract; only declared current code is inspected")
    if any(
        r["config_source"] is not None and r["config_source"] not in CONFIG_SOURCES
        for r in manifest["integrations"]
    ):
        raise ValueError("Unexpected integration configuration source")
    if proposal["authority"] != "not-granted" or manifest["live_verification_receipts"]:
        raise ValueError("This offline inspector cannot confer live-run authority or acceptance")
    ceiling = proposal["aggregate_spend_ceiling_usd"]
    if not math.isfinite(ceiling) or not 0 < ceiling <= 10 or proposal["concurrency_max"] != 1:
        raise ValueError("Proposal weakens the aggregate spend or concurrency bound")
    if sum(p["allocated_spend_ceiling_usd"] for p in plans) > ceiling:
        raise ValueError("Run allocations exceed aggregate spend ceiling")
    for metric in ("generation_or_synthesis_attempts_max", "provider_http_operations_max"):
        total = proposal["total_" + metric]
        if type(total) is not int or total < 1 or sum(p[metric] for p in plans) > total:
            raise ValueError("Run allocations exceed aggregate attempt or operation bound")
    for plan in plans:
        validate_run_bounds(plan, ceiling)
        if (
            plan["state"] != "draft-not-authorized"
            or plan["concurrency_max"] != 1
            or plan["attempts_per_logical_call_max"] != 1
        ):
            raise ValueError("Run plan lacks the fixed authority/concurrency/attempt boundary")
        if not plan["operations_requiring_authorization"] or not plan["launch_blockers"]:
            raise ValueError("Run plan omits operation authority or launch prerequisites")
    validate_development_sources(root, manifest["development_fixtures"])


def inspect_readiness(
    root: Path = ROOT, *, env: dict | None = None, env_file: Path = DEFAULT_ENV_PATH
) -> dict:
    """Build a side-effect-free matrix from current source and local presence."""
    manifest = json.loads((root / MANIFEST).read_text())
    validate_plans(root, manifest)
    resolved = effective_environment(dict(os.environ) if env is None else env, env_file)
    rows = [inspect_integration(root, row, resolved) for row in manifest["integrations"]]
    source_paths = (
        list(manifest["config_sources"].values()) + manifest["additional_source_contracts"]
    )
    return {
        "schema_version": 1,
        "bead_id": manifest["bead_id"],
        "inspection": "read-only-local-presence",
        "network_requests": 0,
        "provider_calls": 0,
        "source_sha256": {p: digest(root / p) for p in source_paths},
        "integrations": rows,
        "proposed_aggregate_spend_ceiling_usd": manifest["live_run_proposal"][
            "aggregate_spend_ceiling_usd"
        ],
        "run_authority": "not-granted",
        "limitations": [
            "Endpoint reachability, scopes, account credit/quota, GPU/physical capacity and provider costs remain unverified.",
            "Credential/model/endpoint/path values are omitted; exact effective settings require a private launch freeze.",
            "No service clients, tracing setup, subprocesses, device operations or heldout inputs are inspected.",
            "Installed/configured/mock states are not live verification; no accepted live provider receipts exist.",
        ],
    }


def main() -> None:
    """Print safe JSON to stdout, with no configuration or artifact writes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    args = parser.parse_args()
    try:
        result = inspect_readiness(env_file=args.env_file)
    except (OSError, ValueError, KeyError, SyntaxError):
        parser.exit(
            1,
            "Readiness inspection failed: declared source/config/development inputs are unavailable or invalid.\n",
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
