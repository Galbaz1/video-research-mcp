"""Verify that programme checks reject omissions and weakened prerequisites."""

import json

import pytest

from scripts.validate_capability_programme import INVENTORY, validate_inventory


def test_unmapped_audited_surface_is_rejected():
    """An audit entry without a mapped tool must prevent a coverage pass."""
    data = json.loads(INVENTORY.read_text())
    data["source_lanes"]["direct"]["coverage"]["public_tool_names"].append("unmapped:test")
    with pytest.raises(ValueError, match="tool coverage: direct"):
        validate_inventory(data)


def test_removed_primary_owner_is_rejected():
    """Removing a transfer unit from its assigned package leaves an orphan."""
    data = json.loads(INVENTORY.read_text())
    package = next(p for p in data["work_packages"] if p["unit_keys"])
    package["unit_keys"].pop()
    with pytest.raises(ValueError, match="orphan unit"):
        validate_inventory(data)


def test_weakened_dependency_is_rejected():
    """A transitive reduction may not discard a declared prerequisite."""
    data = json.loads(INVENTORY.read_text())
    package = next(p for p in data["work_packages"] if p["depends_on"])
    package["depends_on"] = []
    with pytest.raises(ValueError, match="weakened prerequisite"):
        validate_inventory(data)


def test_dependency_cycle_is_rejected():
    """A cyclic plan cannot be handed off as an executable programme."""
    data = json.loads(INVENTORY.read_text())
    data["work_packages"][0]["depends_on"].append(data["work_packages"][0]["key"])
    with pytest.raises(ValueError, match="cycle or missing dependency"):
        validate_inventory(data)


def test_unmapped_overlap_surface_is_rejected():
    """A considered wrapper must retain a destination for each useful surface."""
    data = json.loads(INVENTORY.read_text())
    data["overlap_candidates"][0]["tool_mapping"]["analyze_image"] = []
    with pytest.raises(ValueError, match="unmapped overlap surface"):
        validate_inventory(data)


def test_package_cannot_drop_source_acceptance():
    """Editing a task contract may not discard retained source requirements."""
    data = json.loads(INVENTORY.read_text())
    package = next(p for p in data["work_packages"] if p["key"] == "tts")
    package["acceptance"] = []
    with pytest.raises(ValueError, match="omitted source acceptance"):
        validate_inventory(data)


def test_package_cannot_drop_source_prerequisites():
    """Editing both dependency summaries cannot remove source prerequisites."""
    data = json.loads(INVENTORY.read_text())
    package = next(p for p in data["work_packages"] if p["key"] == "translation")
    package["depends_on"] = []
    package["declared_dependencies"] = []
    with pytest.raises(ValueError, match="omitted source prerequisite"):
        validate_inventory(data)


def test_entire_unit_cannot_be_removed_with_its_surface_summaries():
    """Coordinated removal of hardware and its summaries breaks the frozen audit."""
    data = json.loads(INVENTORY.read_text())
    lane = data["source_lanes"]["qwen"]
    unit = next(u for u in lane["units"] if u["key"] == "qwen_hardware")
    lane["units"].remove(unit)
    for field, unit_field in (
        ("public_tool_names", "public_tools"),
        ("public_workflow_names", "public_workflows"),
    ):
        lane["coverage"][field] = [v for v in lane["coverage"][field] if v not in unit[unit_field]]
    package = next(p for p in data["work_packages"] if p["key"] == "hardware")
    package["unit_keys"] = []
    with pytest.raises(ValueError, match="changed frozen source audit: qwen"):
        validate_inventory(data)


def test_overlap_population_cannot_be_removed():
    """Deleting the considered wrapper cannot silently weaken the audit gate."""
    data = json.loads(INVENTORY.read_text())
    data["overlap_candidates"] = []
    with pytest.raises(ValueError, match="changed frozen overlap audit"):
        validate_inventory(data)
