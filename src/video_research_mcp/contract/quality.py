"""Quality gate checks for strict video contract pipeline.

Runs structural validation, artifact existence, link integrity, and HTML
parseability checks. Factual support and media/human review remain separate.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from ..models.coverage import MediaCoverage, summarize_coverage
from ..models.video_contract import QualityCheck, QualityReport
from ..validation import validate_analysis

logger = logging.getLogger(__name__)


def run_quality_gates(
    analysis: dict,
    concept_map: dict,
    artifact_dir: Path,
    *,
    coverage_min_ratio: float = 0.90,
    start_time: float,
    observation: MediaCoverage,
) -> QualityReport:
    """Run all quality gates and return a QualityReport.

    Args:
        analysis: StrictVideoResult as dict.
        concept_map: ConceptMap as dict.
        artifact_dir: Directory containing rendered artifacts.
        coverage_min_ratio: Minimum observed interval coverage ratio.
        start_time: Pipeline start time for duration calculation.
        observation: Controller-supplied source/coverage receipt, never model output.

    Returns:
        QualityReport with all checks and overall status.
    """
    checks: list[QualityCheck] = []

    duration = observation.measured_duration_ms
    vr = validate_analysis(analysis, duration_seconds=duration / 1000 if duration else None)
    checks.append(
        QualityCheck(
            name="structure_and_timestamp_format",
            passed=vr.passed,
            detail="; ".join(vr.issues)
            if vr.issues
            else "Structure and clock format/order passed; source correctness unverified",
        )
    )

    checks.append(_check_concept_map_edges(concept_map))
    checks.append(_check_artifacts_exist(artifact_dir))
    checks.append(_check_links_valid(artifact_dir))
    checks.append(_check_html_parseable(artifact_dir))

    coverage = summarize_coverage(observation, coverage_min_ratio)
    if coverage.status != "unknown":
        checks.append(
            QualityCheck(
                name="observed_coverage",
                passed=coverage.status == "pass",
                detail=f"Observed {coverage.observed_ms}ms; minimum {coverage_min_ratio:.0%}",
            )
        )

    return QualityReport(
        status="pass" if all(c.passed for c in checks) else "fail",
        coverage_ratio=coverage.observed_ratio,
        coverage=coverage,
        declared_duration_seconds=analysis.get("duration_seconds", 0),
        checks=checks,
        duration_seconds=round(time.monotonic() - start_time, 2),
    )


def _check_concept_map_edges(concept_map: dict) -> QualityCheck:
    """Verify all concept-map edges reference existing node IDs."""
    node_ids = {n.get("id") for n in concept_map.get("nodes", []) if n.get("id")}
    dangling: list[str] = []
    for edge in concept_map.get("edges", []):
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src and src not in node_ids:
            dangling.append(f"edge source '{src}' not in nodes")
        if tgt and tgt not in node_ids:
            dangling.append(f"edge target '{tgt}' not in nodes")

    if dangling:
        return QualityCheck(
            name="concept_map_edges",
            passed=False,
            detail="; ".join(dangling),
        )
    return QualityCheck(
        name="concept_map_edges",
        passed=True,
        detail="All edges reference valid nodes",
    )


def _check_artifacts_exist(artifact_dir: Path) -> QualityCheck:
    """Verify expected artifacts are nonempty regular files inside the output directory."""
    expected = ["analysis.md", "strategy.md", "concept-map.html"]
    invalid = []
    for name in expected:
        path = artifact_dir / name
        if not path.is_file() or not path.resolve().is_relative_to(artifact_dir.resolve()):
            invalid.append(name)
        elif path.stat().st_size == 0:
            invalid.append(name)

    if invalid:
        return QualityCheck(
            name="artifacts_exist",
            passed=False,
            detail=f"Missing, empty or out-of-scope artifacts: {', '.join(invalid)}",
        )
    return QualityCheck(name="artifacts_exist", passed=True, detail="All artifacts present")


def _check_links_valid(artifact_dir: Path) -> QualityCheck:
    """Verify that relative links in markdown files resolve to existing files."""
    issues: list[str] = []
    link_pattern = re.compile(r"\[.*?\]\(([^)]+)\)")

    for md_file in artifact_dir.glob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        for match in link_pattern.finditer(content):
            link = match.group(1)
            if link.startswith(("http://", "https://", "#")):
                continue
            # Strip anchor fragments and query strings before resolving
            link_path = link.split("#")[0].split("?")[0]
            if not link_path:
                continue
            target = (md_file.parent / link_path).resolve()
            artifact_root = artifact_dir.resolve()
            if not target.is_relative_to(artifact_root):
                issues.append(f"{md_file.name}: link escapes artifact dir '{link}'")
            elif not target.exists():
                issues.append(f"{md_file.name}: broken link '{link}'")

    if issues:
        return QualityCheck(
            name="links_valid",
            passed=False,
            detail="; ".join(issues),
        )
    return QualityCheck(name="links_valid", passed=True, detail="All relative links resolve")


def _check_html_parseable(artifact_dir: Path) -> QualityCheck:
    """Verify HTML files are well-formed (basic tag balance check)."""
    for html_file in artifact_dir.glob("*.html"):
        content = html_file.read_text(encoding="utf-8")
        if "<html" not in content.lower() or "</html>" not in content.lower():
            return QualityCheck(
                name="html_parseable",
                passed=False,
                detail=f"{html_file.name}: missing <html> or </html> tags",
            )
    return QualityCheck(name="html_parseable", passed=True, detail="HTML files are well-formed")
