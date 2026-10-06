"""Fresh companion imports and discovery keep optional stock transport parked."""

import subprocess
import sys
import textwrap


def test_public_companion_keeps_local_assembly_and_omits_stock():
    """A clean interpreter discovers assembly without importing remote transport."""
    script = textwrap.dedent("""
        import asyncio
        import socket
        import sys

        def refuse_network(*args, **kwargs):
            raise AssertionError("Network is forbidden in discovery")

        socket.getaddrinfo = refuse_network
        socket.create_connection = refuse_network
        from video_explainer_mcp.server import app
        assert "video_explainer_mcp.materials_remote" not in sys.modules
        names = {tool.name for tool in asyncio.run(app.list_tools())}
        assert "explainer_materials_assemble" in names, names
        assert "explainer_materials_search" not in names, names
        assert "explainer_materials_download" not in names, names
        assert "video_explainer_mcp.materials_remote" not in sys.modules
        assert "video_explainer_mcp.tools.materials_stock" not in sys.modules
    """)
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
