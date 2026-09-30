#!/usr/bin/env python3
"""Verify a built core wheel over stdio without sending provider requests."""

from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def smoke(wheel: Path) -> None:
    """Launch the installed wheel and inspect its public discovery/configuration."""
    wheel = wheel.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="gr-wheel-smoke-") as scratch:
        overrides = {"GEMINI_MODEL", "GEMINI_FLASH_MODEL", "GEMINI_THINKING_LEVEL",
                     "DEEP_RESEARCH_AGENT", "GEMINI_SESSION_DB"}
        env = {key: value for key, value in os.environ.items() if key not in overrides}
        env.update(HOME=scratch, GEMINI_API_KEY="test-key-not-real",
                   GEMINI_TRACING_ENABLED="false", WEAVIATE_URL="", WEAVIATE_API_KEY="",
                   WEAVIATE_VECTORIZER="weaviate")
        transport = StdioTransport(
            command="uv", args=["run", "--no-project", "--with", str(wheel), "video-research-mcp"],
            env=env, cwd=scratch,
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            response = await client.call_tool("infra_configure", {})
            config = response.data["current_config"]
            if (len(tools) != 34 or config["default_model"] != "gemini-3.8-flash"
                    or config["deep_research_agent"] != "deep-research-preview-04-2026"):
                raise RuntimeError("Built artifact tool/model contract differs from this release")
            print("PASS: built wheel stdio discovery (34 tools) and read-only configuration")


def main() -> None:
    """Read the wheel path and perform the offline artifact smoke."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    asyncio.run(smoke(parser.parse_args().wheel))


if __name__ == "__main__":
    main()
