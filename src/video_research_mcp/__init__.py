"""Video Research MCP — unified research partner server."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("video-research-mcp")
except PackageNotFoundError:
    __version__ = "unknown"

