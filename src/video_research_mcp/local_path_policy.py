"""Policy helpers for local filesystem access boundaries."""

from __future__ import annotations

from pathlib import Path

from .config import get_config


def resolve_path(path_value: str) -> Path:
    """Resolve a user-supplied path to an absolute filesystem path."""
    return Path(path_value).expanduser().resolve()


def enforce_local_access_root(path: Path) -> Path:
    """Enforce LOCAL_FILE_ACCESS_ROOT boundary when configured.

    Args:
        path: Absolute filesystem path to validate.

    Returns:
        The original path when allowed.

    Raises:
        PermissionError: If the path falls outside the configured access root.
    """
    cfg = get_config()
    if not cfg.local_file_access_root:
        return path

    root = Path(cfg.local_file_access_root).expanduser().resolve()
    if not path.is_relative_to(root):
        raise PermissionError(
            f"Path '{path}' is outside LOCAL_FILE_ACCESS_ROOT '{root}'"
        )
    return path

