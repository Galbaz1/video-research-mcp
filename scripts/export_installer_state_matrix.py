#!/usr/bin/env python3
"""Export installer state matrix and FILE_MAP integrity checks.

The matrix provides measurable baseline evidence for installer safety work.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MIN_SCENARIO_COUNT = 20

SCENARIOS: list[dict[str, Any]] = [
    # Install path
    {
        "id": "fresh_global_install",
        "category": "install",
        "risk": "high",
        "description": "Install globally into an empty ~/.claude tree.",
        "expected": ["files_copied", "manifest_created", "mcp_servers_registered"],
    },
    {
        "id": "fresh_local_install",
        "category": "install",
        "risk": "medium",
        "description": "Install locally into project .claude directory.",
        "expected": ["files_copied", "manifest_created", "mcp_servers_registered"],
    },
    {
        "id": "global_install_without_existing_mcp_json",
        "category": "install",
        "risk": "medium",
        "description": "Create .mcp.json when none exists.",
        "expected": ["mcp_json_created", "servers_registered"],
    },
    {
        "id": "global_install_with_existing_mcp_json",
        "category": "install",
        "risk": "high",
        "description": "Merge with existing .mcp.json preserving user-managed server entries.",
        "expected": ["user_entries_preserved", "managed_entries_updated"],
    },
    {
        "id": "local_install_permissions_error",
        "category": "install",
        "risk": "high",
        "description": "Handle write-permission errors without partial state corruption.",
        "expected": ["clean_failure", "actionable_error"],
    },
    # Upgrade path
    {
        "id": "upgrade_unmodified",
        "category": "upgrade",
        "risk": "high",
        "description": "Upgrade when all managed files are unmodified.",
        "expected": ["safe_overwrite", "obsolete_cleanup", "manifest_updated"],
    },
    {
        "id": "upgrade_with_user_edits",
        "category": "upgrade",
        "risk": "critical",
        "description": "Upgrade with user-modified managed files.",
        "expected": ["edited_files_preserved", "conflict_reported", "force_required"],
    },
    {
        "id": "force_upgrade_with_user_edits",
        "category": "upgrade",
        "risk": "high",
        "description": "Force upgrade replacing user-modified files.",
        "expected": ["edited_files_overwritten", "manifest_updated"],
    },
    {
        "id": "upgrade_removes_obsolete_files",
        "category": "upgrade",
        "risk": "medium",
        "description": "Remove obsolete files listed in old manifest but not current FILE_MAP.",
        "expected": ["obsolete_files_removed", "cleanup_completed"],
    },
    {
        "id": "upgrade_with_corrupt_manifest",
        "category": "upgrade",
        "risk": "high",
        "description": "Recover gracefully when manifest JSON is malformed.",
        "expected": ["manifest_rebuilt_or_error", "no_unbounded_deletes"],
    },
    {
        "id": "upgrade_when_manifest_missing",
        "category": "upgrade",
        "risk": "medium",
        "description": "Upgrade in environments where manifest was deleted manually.",
        "expected": ["best_effort_update", "manifest_recreated"],
    },
    {
        "id": "upgrade_cross_platform_path_separators",
        "category": "upgrade",
        "risk": "medium",
        "description": "Verify path normalization for unix/windows style separators.",
        "expected": ["path_normalization", "no_duplicate_targets"],
    },
    # Uninstall path
    {
        "id": "uninstall_clean",
        "category": "uninstall",
        "risk": "high",
        "description": "Uninstall when managed files match manifest hashes.",
        "expected": ["managed_files_removed", "empty_dirs_cleaned", "manifest_removed"],
    },
    {
        "id": "uninstall_with_user_edits",
        "category": "uninstall",
        "risk": "critical",
        "description": "Uninstall when managed files were user modified.",
        "expected": ["user_files_preserved", "safety_warnings_emitted"],
    },
    {
        "id": "uninstall_without_manifest",
        "category": "uninstall",
        "risk": "medium",
        "description": "Uninstall when manifest is already missing.",
        "expected": ["no_crash", "best_effort_cleanup"],
    },
    {
        "id": "uninstall_partial_files_missing",
        "category": "uninstall",
        "risk": "low",
        "description": "Uninstall when some managed files are already deleted.",
        "expected": ["idempotent_remove", "warnings_optional"],
    },
    # Config merge path
    {
        "id": "mcp_merge_preserves_custom_env",
        "category": "config_merge",
        "risk": "high",
        "description": "Preserve existing env values for unrelated servers.",
        "expected": ["foreign_env_preserved", "managed_servers_present"],
    },
    {
        "id": "mcp_merge_updates_managed_server_args",
        "category": "config_merge",
        "risk": "high",
        "description": "Update managed server args to latest expected values.",
        "expected": ["managed_args_updated", "json_valid"],
    },
    {
        "id": "mcp_merge_with_empty_mcpServers",
        "category": "config_merge",
        "risk": "medium",
        "description": "Handle configs with empty mcpServers object.",
        "expected": ["servers_inserted", "json_valid"],
    },
    {
        "id": "mcp_merge_with_additional_top_level_keys",
        "category": "config_merge",
        "risk": "medium",
        "description": "Preserve non-mcp top-level keys during merge.",
        "expected": ["top_level_keys_preserved", "managed_servers_present"],
    },
    # Integrity and safety path
    {
        "id": "file_map_missing_source_detection",
        "category": "integrity",
        "risk": "critical",
        "description": "Detect missing source files referenced by FILE_MAP.",
        "expected": ["integrity_fail", "missing_sources_reported"],
    },
    {
        "id": "file_map_duplicate_destination_detection",
        "category": "integrity",
        "risk": "critical",
        "description": "Detect duplicate destination collisions in FILE_MAP.",
        "expected": ["integrity_fail", "duplicate_destinations_reported"],
    },
]


def _load_file_map() -> dict[str, str]:
    """Load FILE_MAP from Node module."""
    result = subprocess.run(
        [
            "node",
            "-e",
            "const m=require('./bin/lib/copy.js');console.log(JSON.stringify(m.FILE_MAP));",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _validate_file_map(file_map: dict[str, str]) -> dict[str, Any]:
    """Validate that all source files exist and destinations are unique."""
    missing_sources = [src for src in file_map if not Path(src).exists()]
    destinations = list(file_map.values())
    duplicate_destinations = sorted({d for d in destinations if destinations.count(d) > 1})
    categories = {
        "commands": sum(1 for src in file_map if src.startswith("commands/")),
        "skills": sum(1 for src in file_map if src.startswith("skills/")),
        "agents": sum(1 for src in file_map if src.startswith("agents/")),
    }
    return {
        "entry_count": len(file_map),
        "missing_source_count": len(missing_sources),
        "missing_sources": missing_sources,
        "duplicate_destination_count": len(duplicate_destinations),
        "duplicate_destinations": duplicate_destinations,
        "categories": categories,
        "integrity_pass": not missing_sources and not duplicate_destinations,
    }


def _build_scenario_summary(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize scenarios by category and risk level."""
    category_counts = Counter(item["category"] for item in scenarios)
    risk_counts = Counter(item["risk"] for item in scenarios)
    return {
        "total": len(scenarios),
        "by_category": dict(sorted(category_counts.items())),
        "by_risk": dict(sorted(risk_counts.items())),
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="docs/metrics/installer-state-matrix.json",
        help="Output path for installer matrix JSON.",
    )
    parser.add_argument(
        "--min-scenarios",
        type=int,
        default=MIN_SCENARIO_COUNT,
        help="Fail if scenario count is below this threshold.",
    )
    return parser.parse_args()


def main() -> None:
    """Script entry point."""
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if len(SCENARIOS) < args.min_scenarios:
        raise SystemExit(
            f"Scenario count {len(SCENARIOS)} is below required minimum {args.min_scenarios}"
        )

    file_map = _load_file_map()
    integrity = _validate_file_map(file_map)
    scenario_summary = _build_scenario_summary(SCENARIOS)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "quality_gates": {
            "min_scenario_count": args.min_scenarios,
            "actual_scenario_count": len(SCENARIOS),
            "scenario_count_pass": len(SCENARIOS) >= args.min_scenarios,
            "file_map_integrity_pass": integrity["integrity_pass"],
        },
        "file_map_integrity": integrity,
        "scenario_summary": scenario_summary,
        "scenarios": SCENARIOS,
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(
        "Wrote installer matrix with "
        f"{len(SCENARIOS)} scenarios and {integrity['entry_count']} FILE_MAP entries to {output_path}"
    )


if __name__ == "__main__":
    main()
