"""Collect one local video source over stdio; inference is never invoked."""

import argparse
import asyncio
import json
from pathlib import Path

from video_research_mcp.integrations.external_harness import FrameRequest, load_settings, query_source


def main() -> None:
    """Write a fresh complete or failed source receipt without overwriting prior evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = FrameRequest(file_path=args.source, expected_source_sha256=args.source_sha256,
                           time_seconds=args.seconds)
    settings = load_settings(args.settings)
    with args.output.open("x", encoding="utf-8") as stream:
        result = asyncio.run(query_source(settings, request))
        json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
    print(result["status"])
    raise SystemExit(0 if result["status"] == "complete" else 1)


if __name__ == "__main__":
    main()
