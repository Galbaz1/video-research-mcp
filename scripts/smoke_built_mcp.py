#!/usr/bin/env python3
"""Verify a built core wheel over stdio without sending provider requests."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


SOURCE_CONTRACT_CODE = """
import asyncio, json
from video_research_mcp.server import app
async def run():
    tools = await app.list_tools()
    return [tool.to_mcp_tool().model_dump(by_alias=True, exclude_none=True)
            for tool in sorted(tools, key=lambda tool: tool.name)]
print(json.dumps(asyncio.run(run())))
"""


def check_tool_contract(tools: list, expected: list[dict]) -> None:
    """Reject missing, extra or changed wire contracts in the installed wheel."""
    actual = [
        tool.model_dump(by_alias=True, exclude_none=True)
        for tool in sorted(tools, key=lambda tool: tool.name)
    ]
    if actual != expected:
        raise RuntimeError("Built artifact tool contract differs from candidate source")


async def media_journey(client: Client, scratch: Path) -> None:
    """Check actual native/text crop transports using owned synthetic PNG bytes."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("Native media smoke requires independently installed FFmpeg")

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    source = scratch / "owned-blue.png"
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
    data += chunk(b"IDAT", zlib.compress((b"\x00" + b"\x00\x00\xff" * 4) * 4)) + chunk(b"IEND", b"")
    source.write_bytes(data)
    source_hash = hashlib.sha256(data).hexdigest()
    results = []
    for mode in (True, False):
        result = await client.call_tool(
            "image_crop",
            {
                "file_path": str(source),
                "output_path": str(scratch / f"crop-{mode}.png"),
                "crop_box": [1, 1, 2, 2],
                "include_image": mode,
            },
        )
        metadata = result.structured_content
        assert metadata["source_sha256"] == source_hash
        assert metadata["crop_box"] == [1, 1, 2, 2]
        assert json.loads(result.content[0].text) == metadata
        assert [block.type for block in result.content] == (["text", "image"] if mode else ["text"])
        artifact = Path(metadata["artifact"]).read_bytes()
        assert hashlib.sha256(artifact).hexdigest() == metadata["artifact_sha256"]
        if mode:
            assert base64.b64decode(result.content[1].data) == artifact
        results.append(metadata)
    assert results[0]["artifact_sha256"] == results[1]["artifact_sha256"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    print("PASS: native/text PNG transport, source/crop identity and artifact hashes")


async def smoke(wheel: Path) -> None:
    """Launch the installed wheel and inspect its public discovery/configuration."""
    wheel = wheel.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="gr-wheel-smoke-") as scratch:
        overrides = {
            "GEMINI_MODEL",
            "GEMINI_FLASH_MODEL",
            "GEMINI_THINKING_LEVEL",
            "DEEP_RESEARCH_AGENT",
            "GEMINI_SESSION_DB",
            "PYTHONPATH",
        }
        env = {key: value for key, value in os.environ.items() if key not in overrides}
        env.update(
            HOME=scratch,
            GEMINI_API_KEY="test-key-not-real",
            GEMINI_TRACING_ENABLED="false",
            S2_API_KEY="built-wheel-secret-sentinel",
            WEAVIATE_URL="",
            WEAVIATE_API_KEY="",
            WEAVIATE_VECTORIZER="weaviate",
        )
        env["VIDEO_RESEARCH_ENV_FILE"] = str(Path(scratch) / "absent.env")
        env.setdefault(
            "UV_CACHE_DIR", subprocess.check_output(["uv", "cache", "dir"], text=True).strip()
        )
        source_env = {**env, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
        expected = json.loads(
            subprocess.check_output(
                [sys.executable, "-c", SOURCE_CONTRACT_CODE],
                env=source_env,
                cwd=scratch,
                text=True,
            )
        )
        transport = StdioTransport(
            command="uv",
            args=["run", "--no-project", "--with", str(wheel), "video-research-mcp"],
            env=env,
            cwd=scratch,
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            check_tool_contract(tools, expected)
            response = await client.call_tool("infra_configure", {})
            config = response.data["current_config"]
            if (
                config["default_model"] != "gemini-3.8-flash"
                or config["deep_research_agent"] != "deep-research-preview-04-2026"
            ):
                raise RuntimeError("Built artifact model configuration differs from this release")
            if "s2_api_key" in config or "built-wheel-secret-sentinel" in str(response.data):
                raise RuntimeError("Built artifact exposes the Semantic Scholar API key")
            print(
                f"PASS: built wheel matches all {len(tools)} source tool contracts; "
                "configuration and secret redaction"
            )
            await media_journey(client, Path(scratch))


def main() -> None:
    """Read the wheel path and perform the offline artifact smoke."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    asyncio.run(smoke(parser.parse_args().wheel))


if __name__ == "__main__":
    main()
