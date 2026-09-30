"""Artifact rendering for strict video contract pipeline.

Generates markdown and HTML files from structured analysis results:
- analysis.md — main analysis with timestamps and key points
- strategy.md — strategic report derived from the analysis
- concept-map.html — self-contained HTML with inline SVG concept map
"""

from __future__ import annotations

import html
from pathlib import Path

# Localizable section headers keyed by ISO 639-1 code.
# English is the fallback for any unrecognized language.
_HEADERS: dict[str, dict[str, str]] = {
    "en": {
        "summary": "Summary",
        "key_points": "Key Points",
        "timestamps": "Timestamps",
        "topics": "Topics",
        "strategy_notes": "Strategic Notes",
        "concept_map": "Concept Map",
        "source": "Source",
        "see_also": "See also",
        "review_status": "Draft: source support, timestamp correctness and media/human review are pending. Observed video coverage is unknown.",
    },
    "nl": {
        "summary": "Samenvatting",
        "key_points": "Kernpunten",
        "timestamps": "Tijdstempels",
        "topics": "Onderwerpen",
        "strategy_notes": "Strategische Notities",
        "concept_map": "Conceptkaart",
        "source": "Bron",
        "see_also": "Zie ook",
        "review_status": "Concept: bronondersteuning, juistheid van tijdstempels en media-/menselijke controle zijn nog niet beoordeeld. Geobserveerde videodekking is onbekend.",
    },
    "es": {
        "summary": "Resumen",
        "key_points": "Puntos Clave",
        "timestamps": "Marcas de Tiempo",
        "topics": "Temas",
        "strategy_notes": "Notas Estratégicas",
        "concept_map": "Mapa Conceptual",
        "source": "Fuente",
        "see_also": "Ver también",
        "review_status": "Borrador: el respaldo de fuentes, los tiempos y la revisión humana y de medios están pendientes. La cobertura observada es desconocida.",
    },
}


def _get_headers(lang: str) -> dict[str, str]:
    """Return localized headers, falling back to English."""
    return _HEADERS.get(lang, _HEADERS["en"])


def render_artifacts(
    output_dir: Path,
    analysis: dict,
    strategy: dict,
    concept_map: dict,
    *,
    source_label: str,
    report_language: str = "en",
) -> dict[str, str]:
    """Render all artifacts to the output directory.

    Args:
        output_dir: Directory to write files into (must exist).
        analysis: StrictVideoResult as dict.
        strategy: StrategyReport as dict.
        concept_map: ConceptMap as dict.
        source_label: Video source URL or file path.
        report_language: ISO 639-1 language code for report headers.

    Returns:
        Dict mapping artifact name to file path.
    """
    headers = _get_headers(report_language)
    paths: dict[str, str] = {}

    analysis_path = output_dir / "analysis.md"
    _render_analysis_md(analysis_path, analysis, source_label, headers)
    paths["analysis"] = str(analysis_path)

    strategy_path = output_dir / "strategy.md"
    _render_strategy_md(strategy_path, strategy, headers)
    paths["strategy"] = str(strategy_path)

    concept_path = output_dir / "concept-map.html"
    _render_concept_map_html(concept_path, concept_map, headers)
    paths["concept_map"] = str(concept_path)

    return paths


def _render_analysis_md(path: Path, analysis: dict, source: str, h: dict[str, str]) -> None:
    """Write the main analysis markdown file."""
    lines: list[str] = []
    title = analysis.get("title", "Video Analysis")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**{h['source']}:** {source}")
    lines.append("")
    lines.extend([h["review_status"], ""])

    if analysis.get("summary"):
        lines.append(f"## {h['summary']}")
        lines.append("")
        lines.append(analysis["summary"])
        lines.append("")

    if analysis.get("key_points"):
        lines.append(f"## {h['key_points']}")
        lines.append("")
        for point in analysis["key_points"]:
            lines.append(f"- {point}")
        lines.append("")

    if analysis.get("timestamps"):
        lines.append(f"## {h['timestamps']}")
        lines.append("")
        lines.append("| Time | Description |")
        lines.append("|------|-------------|")
        for ts in analysis["timestamps"]:
            time_val = ts.get("time", "") if isinstance(ts, dict) else ""
            desc = ts.get("description", "") if isinstance(ts, dict) else ""
            lines.append(f"| {time_val} | {desc} |")
        lines.append("")

    if analysis.get("topics"):
        lines.append(f"## {h['topics']}")
        lines.append("")
        lines.append(", ".join(analysis["topics"]))
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        f"{h['see_also']}: [Strategy Report](strategy.md) | [{h['concept_map']}](concept-map.html)"
    )
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _render_strategy_md(path: Path, strategy: dict, h: dict[str, str]) -> None:
    """Write the strategy report markdown file."""
    lines: list[str] = []
    lines.append(f"# {strategy.get('title', 'Strategy Report')}")
    lines.append("")
    lines.extend([h["review_status"], ""])

    for section in strategy.get("sections", []):
        lines.append(f"## {section.get('heading', 'Section')}")
        lines.append("")
        lines.append(section.get("content", ""))
        lines.append("")

    if strategy.get("strategic_notes"):
        lines.append(f"## {h['strategy_notes']}")
        lines.append("")
        for note in strategy["strategic_notes"]:
            lines.append(f"- {note}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _render_concept_map_html(path: Path, concept_map: dict, h: dict[str, str]) -> None:
    """Write a self-contained HTML file with an inline SVG concept map."""
    nodes = concept_map.get("nodes", [])
    edges = concept_map.get("edges", [])

    node_positions = _layout_nodes(nodes)
    svg_elements: list[str] = []

    # Draw edges first (behind nodes)
    for edge in edges:
        src = node_positions.get(edge.get("source", ""))
        tgt = node_positions.get(edge.get("target", ""))
        if src and tgt:
            label = html.escape(edge.get("label", ""))
            mid_x = (src[0] + tgt[0]) / 2
            mid_y = (src[1] + tgt[1]) / 2
            svg_elements.append(
                f'  <line x1="{src[0]}" y1="{src[1]}" x2="{tgt[0]}" y2="{tgt[1]}" '
                f'stroke="#666" stroke-width="2" marker-end="url(#arrow)"/>'
            )
            if label:
                svg_elements.append(
                    f'  <text x="{mid_x}" y="{mid_y - 8}" text-anchor="middle" '
                    f'font-size="11" fill="#888">{label}</text>'
                )

    # Draw nodes
    for node in nodes:
        pos = node_positions.get(node.get("id", ""))
        if pos:
            label = html.escape(node.get("label", ""))
            svg_elements.append(
                f'  <circle cx="{pos[0]}" cy="{pos[1]}" r="30" '
                f'fill="#4a90d9" stroke="#2c5f8a" stroke-width="2"/>'
            )
            svg_elements.append(
                f'  <text x="{pos[0]}" y="{pos[1] + 4}" text-anchor="middle" '
                f'font-size="12" fill="white" font-weight="bold">{label}</text>'
            )

    svg_content = "\n".join(svg_elements)
    width = max((p[0] for p in node_positions.values()), default=200) + 100
    height = max((p[1] for p in node_positions.values()), default=200) + 100

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{h["concept_map"]}</title>
<style>body {{ font-family: sans-serif; margin: 20px; background: #f5f5f5; }}</style>
</head>
<body>
<h1>{h["concept_map"]}</h1>
<p>{html.escape(h["review_status"])}</p>
<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#666"/>
    </marker>
  </defs>
{svg_content}
</svg>
</body>
</html>"""

    path.write_text(html_content, encoding="utf-8")


def _layout_nodes(nodes: list[dict]) -> dict[str, tuple[float, float]]:
    """Simple grid layout for concept map nodes.

    Returns:
        Dict mapping node id to (x, y) position.
    """
    positions: dict[str, tuple[float, float]] = {}
    cols = max(int(len(nodes) ** 0.5), 1)
    spacing_x = 160
    spacing_y = 120

    for i, node in enumerate(nodes):
        col = i % cols
        row = i // cols
        x = 80 + col * spacing_x
        y = 80 + row * spacing_y
        positions[node.get("id", f"node_{i}")] = (x, y)

    return positions
