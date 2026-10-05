"""Runtime tree commitments require complete, readable directory populations."""

import errno
import os
from pathlib import Path

import pytest

from video_explainer_mcp.render_authored import tree_revision


@pytest.mark.parametrize("blocked_directory", ["root", "nested"])
def test_unreadable_directory_preserves_filesystem_error(tmp_path, monkeypatch, blocked_directory):
    """Unreadable root or nested entries must refuse an empty or partial commitment."""
    tree = tmp_path / "runtime"
    nested = tree / "resources"
    nested.mkdir(parents=True)
    (tree / "manifest.json").write_bytes(b'{"version":1}')
    (nested / "data.bin").write_bytes(b"\x00\x01\x02")
    blocked = tree if blocked_directory == "root" else nested
    error = PermissionError(errno.EACCES, "Directory enumeration denied", str(blocked))
    scandir = os.scandir

    def unreadable_directory(path):
        if Path(path) == blocked:
            raise error
        return scandir(path)

    monkeypatch.setattr(os, "scandir", unreadable_directory)

    with pytest.raises(PermissionError) as raised:
        tree_revision(tree)

    assert raised.value is error


def test_readable_tree_retains_digest_and_confined_symlinks(tmp_path, monkeypatch):
    """Known bytes and link texts keep their digest without traversing directory links."""
    tree = tmp_path / "runtime"
    nested = tree / "resources"
    nested.mkdir(parents=True)
    (tree / "empty").mkdir()
    (tree / "manifest.json").write_bytes(b'{"version":1}')
    (nested / "data.bin").write_bytes(b"\x00\x01\x02")
    (tree / "data-link").symlink_to("resources/data.bin")
    directory_link = tree / "resource-link"
    directory_link.symlink_to("resources", target_is_directory=True)
    scandir = os.scandir

    def refuse_directory_link_traversal(path):
        assert Path(path) != directory_link
        return scandir(path)

    monkeypatch.setattr(os, "scandir", refuse_directory_link_traversal)

    assert tree_revision(tree) == "e7f253f131c3a3352096efadb240f4771bcc7d806357527e55789fbfc0c8e5d7"
