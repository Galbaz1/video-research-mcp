#!/usr/bin/env python3
"""Export the FastMCP tool contract manifest as JSON.

This script captures a reproducible snapshot of the currently mounted tools,
including parameter schemas, output schemas, and tool annotations.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _to_jsonable(value: Any) -> Any:
    """Convert nested objects to JSON-safe structures."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if hasattr(value, "model_dump"):
        return _to_jsonable(value.model_dump())
    if hasattr(value, "dict"):
        return _to_jsonable(value.dict())
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


async def _build_manifest() -> dict[str, Any]:
    """Build tool manifest for the mounted root server."""
    from video_research_mcp.server import app

    tools = await app.list_tools()
    tool_entries: list[dict[str, Any]] = []

    for tool in sorted(tools, key=lambda t: t.name):
        tool_entries.append(
            {
                "name": tool.name,
                "description": tool.description,
                "annotations": _to_jsonable(getattr(tool, "annotations", None)),
                "parameters": _to_jsonable(getattr(tool, "parameters", None)),
                "output_schema": _to_jsonable(getattr(tool, "output_schema", None)),
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool_count": len(tool_entries),
        "tools": tool_entries,
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="docs/metrics/tool-contract-manifest.json",
        help="Output file path for the JSON manifest.",
    )
    return parser.parse_args()


def main() -> None:
    """Script entry point."""
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = asyncio.run(_build_manifest())
    output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote tool manifest with {manifest['tool_count']} tools to {output_path}")


if __name__ == "__main__":
    main()
