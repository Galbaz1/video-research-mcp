"""Check audited surface coverage and its live Beads execution graph."""

import hashlib
import json
import subprocess
from pathlib import Path

INVENTORY = Path(__file__).resolve().parents[1] / (
    "docs/research/2026-09-30-capability-transfer.json"
)

# These fingerprints retain the terminal source audits, independent of editable
# task mappings. A new audit/comparison version requires an explicit new baseline.
SOURCE_AUDITS = {
    "qwen": "349d2dc3a1d030dcc775ba31153346f266075a33618fb763daa3b164c2e769c9",
    "direct": "9c978ddae14b0da6861d8fa2b7a5a623c3105885a929f65e0b455cfc12f6c71a",
    "adjacent": "69265699d97bff9ad09124078056e8553b5c1b60fad8504306a121e999ff094a",
    "own": "c4e2b9f05f1a83dd0ee4461bd1b852e57357da3ecbc300205c6945402e105af8",
}
SOURCE_FIELDS = (
    "key",
    "source_repo",
    "source_revision",
    "source_paths",
    "license",
    "reuse_mode",
    "acceptance",
    "dependencies",
    "public_tools",
    "public_workflows",
)
REPLACED_DEPENDENCIES = {
    ("adj_tts_audio", "adj_storyboard_sync"),
    ("direct.identity", "direct.acquisition"),
}
OVERLAP_AUDIT = "5ad784dcc2ebbbe2ab3d2d57e94932920d8685422769940058b6c21669b71c49"


def require(condition: bool, message: str) -> None:
    """Fail the preparation gate with a concrete inconsistency."""
    if not condition:
        raise ValueError(message)


def validate_surfaces(lane_name: str, lane: dict) -> None:
    """Check each lane's exact tool and workflow union against its audit."""
    tools = {t for u in lane["units"] for t in u["public_tools"]}
    workflows = {t for u in lane["units"] for t in u["public_workflows"]}
    workflow_key = "public_workflow_names" if lane_name == "qwen" else "public_workflows"
    require(tools == set(lane["coverage"]["public_tool_names"]), f"tool coverage: {lane_name}")
    require(workflows == set(lane["coverage"][workflow_key]), f"workflow coverage: {lane_name}")
    if lane_name == "qwen":
        inventory = {
            entry["path"].split("/")[2] + "." + entry["name"]
            for entry in lane["coverage"]["tool_source_inventory"]
        }
        exports = {
            capability + "." + name
            for capability, names in lane["coverage"]["public_tools_by_capability"].items()
            for name in names
        }
        require(tools == inventory == exports, "source tool inventory: qwen")
    elif lane_name == "direct":
        inventory = {
            tool
            for project in lane["coverage"]["project_inventories"]
            for tool in project["public_tools"]
        }
        require(tools == inventory, "source tool inventory: direct")


def validate_source_audit(lane_name: str, lane: dict) -> None:
    """Retain the exact audited unit population, surfaces and source contracts."""
    projection = [
        {field: unit[field] for field in SOURCE_FIELDS}
        for unit in sorted(lane["units"], key=lambda unit: unit["key"])
    ]
    raw = json.dumps(projection, sort_keys=True, separators=(",", ":")).encode()
    require(
        hashlib.sha256(raw).hexdigest() == SOURCE_AUDITS[lane_name],
        f"changed frozen source audit: {lane_name}",
    )


def validate_dependencies(packages: dict) -> dict:
    """Reject cycles, missing prerequisites and weakened transitive dependencies."""
    done, pending = set(), set(packages)
    while pending:
        ready = {key for key in pending if set(packages[key]["depends_on"]) <= done}
        require(bool(ready), f"cycle or missing dependency: {sorted(pending)}")
        done.update(ready)
        pending.difference_update(ready)
    all_ancestors = {}
    for key, package in packages.items():
        ancestors, remaining = set(), list(package["depends_on"])
        while remaining:
            dependency = remaining.pop()
            if dependency not in ancestors:
                ancestors.add(dependency)
                remaining.extend(packages[dependency]["depends_on"])
        require(
            set(package["declared_dependencies"]) <= ancestors,
            f"weakened prerequisite: {key}",
        )
        all_ancestors[key] = ancestors
    return all_ancestors


def validate_source_contracts(data: dict, packages: dict, units: dict, ancestors: dict) -> None:
    """Require source criteria and effective prerequisites in their assigned tasks."""
    changes = {(a["unit"], a["removed_dependency"]) for a in data["dependency_adjustments"]}
    require(changes == REPLACED_DEPENDENCIES, "changed source dependency adjustments")
    for unit in units.values():
        owner = unit["work_package"]
        require(
            set(unit["acceptance"]) <= set(packages[owner]["acceptance"]),
            f"omitted source acceptance: {unit['key']}",
        )
        for dependency in unit["dependencies"]:
            if (unit["key"], dependency) in REPLACED_DEPENDENCIES:
                continue
            prerequisite = units[dependency]["work_package"]
            require(
                prerequisite == owner or prerequisite in ancestors[owner],
                f"omitted source prerequisite: {unit['key']} -> {dependency}",
            )
    for key, package in packages.items():
        require(bool(package["acceptance"]), f"empty package contract: {key}")
        require(
            set(package.get("acceptance_extra", [])) <= set(package["acceptance"]),
            f"omitted control acceptance: {key}",
        )
    for owner, prerequisite in (("timing", "tts"), ("acquisition", "cache")):
        require(prerequisite in ancestors[owner], f"missing replacement edge: {owner}")


def validate_overlap(data: dict, packages: dict) -> None:
    """Retain considered candidate surfaces while allowing explicit task remapping."""
    fields = ("repo", "sha", "source_paths", "license", "public_tools", "public_workflows")
    projection = [
        {field: candidate[field] for field in fields}
        for candidate in sorted(data["overlap_candidates"], key=lambda c: c["repo"])
    ]
    raw = json.dumps(projection, sort_keys=True, separators=(",", ":")).encode()
    require(hashlib.sha256(raw).hexdigest() == OVERLAP_AUDIT, "changed frozen overlap audit")
    for candidate in data["overlap_candidates"]:
        for surface, mapping in (
            ("public_tools", "tool_mapping"),
            ("public_workflows", "workflow_mapping"),
        ):
            require(set(candidate[surface]) == set(candidate[mapping]), "overlap coverage")
            for targets in candidate[mapping].values():
                require(bool(targets), "unmapped overlap surface")
                for target in targets:
                    package = packages[target["work_package"]]
                    require(package["bead_id"] == target["bead_id"], "wrong overlap Bead")


def validate_counts(data: dict, packages: dict, units: dict) -> None:
    """Keep displayed population counts consistent with retained evidence."""
    tools = {t for unit in units.values() for t in unit["public_tools"]}
    workflows = {t for unit in units.values() for t in unit["public_workflows"]}
    repos = {
        s["repo"]
        for name, lane in data["source_lanes"].items()
        if name != "own"
        for s in lane["source_revisions"]
    }
    expected = {
        "transfer_units": len(units),
        "work_packages": len(packages),
        "tool_references": len(tools),
        "workflow_references": len(workflows),
        "external_projects": len(repos),
        "direct_source_registered_tools": 186,
        "direct_document_referenced_external_tools": 24,
        "overlap_candidate_tool_references": 8,
        "overlap_candidate_workflow_references": 1,
    }
    require(data["surface_counts"] == expected, "inconsistent surface counts")


def validate_inventory(data: dict) -> dict:
    """Reject incomplete source records, orphan units and ambiguous ownership."""
    packages = {p["key"]: p for p in data["work_packages"]}
    require(len(packages) == len(data["work_packages"]), "duplicate package keys")
    validate_overlap(data, packages)
    units = {}
    require(set(data["source_lanes"]) == set(SOURCE_AUDITS), "changed audited source lanes")
    for lane_name, lane in data["source_lanes"].items():
        validate_source_audit(lane_name, lane)
        validate_surfaces(lane_name, lane)
        sources = {(source["repo"], source["sha"]) for source in lane["source_revisions"]}
        for unit in lane["units"]:
            key = unit["key"]
            require(key not in units, f"duplicate unit: {key}")
            units[key] = unit
            require(
                (unit["source_repo"], unit["source_revision"]) in sources,
                f"missing pinned source: {key}",
            )
            for field in (
                "source_revision",
                "source_paths",
                "source_urls",
                "license",
                "reuse_mode",
                "acceptance",
                "target_paths",
            ):
                require(bool(unit[field]), f"missing {field}: {key}")
            package = packages[unit["work_package"]]
            require(key in package["unit_keys"], f"orphan unit: {key}")
            require(unit["bead_id"] == package["bead_id"], f"wrong Bead: {key}")
    assigned = [key for package in packages.values() for key in package["unit_keys"]]
    require(len(assigned) == len(set(assigned)), "multiple primary owners for a unit")
    require(set(assigned) == set(units), "unmapped or unknown transfer units")
    require(len({p["bead_id"] for p in packages.values()}) == len(packages), "duplicate Bead")
    ancestors = validate_dependencies(packages)
    validate_source_contracts(data, packages, units, ancestors)
    validate_counts(data, packages, units)
    return packages


def validate_beads(data: dict, issues: list[dict]) -> None:
    """Check actual Beads IDs, ancestry, acceptance and blocking dependencies."""
    by_id = {issue["id"]: issue for issue in issues}
    epic, prep = data["programme"]["epic"], data["programme"]["preparation"]
    require(epic in by_id and prep in by_id, "missing programme/preparation Bead")
    families = {f["key"]: f["bead_id"] for f in data["family_epics"]}
    for family in families.values():
        require(by_id[family]["parent"] == epic, f"wrong family parent: {family}")
    packages = {p["key"]: p for p in data["work_packages"]}
    for package in packages.values():
        issue = by_id[package["bead_id"]]
        key = package["key"]
        require(issue["parent"] == families[package["family"]], f"wrong parent: {key}")
        for field in ("description", "acceptance_criteria", "design"):
            require(bool(issue[field]), f"missing {field}: {key}")
        for criterion in package["acceptance"]:
            require(criterion in issue["acceptance_criteria"], f"weakened acceptance: {key}")
        actual = {
            d["depends_on_id"] for d in issue.get("dependencies", []) if d["type"] == "blocks"
        }
        expected = {packages[k]["bead_id"] for k in package["depends_on"]} or {prep}
        require(actual == expected, f"dependency mismatch: {key}")


def main() -> None:
    """Read the pinned inventory and validate its current local tracker graph."""
    data = json.loads(INVENTORY.read_text())
    validate_inventory(data)
    result = subprocess.run(
        [
            "bd",
            "--readonly",
            "list",
            "--all",
            "--label",
            "capability-programme",
            "--limit",
            "0",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    validate_beads(data, json.loads(result.stdout))
    count = sum(len(lane["units"]) for lane in data["source_lanes"].values())
    print(
        f"PASS: {count} transfer units; {len(data['work_packages'])} work packages; "
        "exact audited/overlap surface coverage and live Beads edges"
    )


if __name__ == "__main__":
    main()
