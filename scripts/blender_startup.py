"""Initialize an owned factory GUI session with the original pinned Blender addon.

Addon registration/startup policy is locally adapted from MIT blender-mcp,
© 2025 Siddharth Ahuja. The external source and full grants remain unmodified.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

from urllib.parse import urlsplit

sys.dont_write_bytecode = True

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_session import (  # noqa: E402
    CREDENTIALS, FLAGS, PACKAGE, admit_binary, admit_sources, expected_identity,
)

DENIAL_LOG = None


def deny_requests(*args, **kwargs):
    """Deny provider/asset HTTP immediately throughout this disposable session."""
    request = args[1] if len(args) > 1 else kwargs.get("request")
    target = urlsplit(getattr(request, "url", "") or "")
    method = getattr(request, "method", "OTHER")
    method = method if method in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS") else "OTHER"
    if DENIAL_LOG is not None:
        with DENIAL_LOG.open("a") as log:
            log.write(json.dumps({"method": method, "scheme": target.scheme,
                                  "host": target.hostname}) + "\n")
    raise RuntimeError("Provider and external asset transport is disabled in this session")


def initialize(addon, bpy, requests, session: dict):
    """Register without a default listener, then start only the owned loopback server."""
    requests.Session.send = deny_requests
    original_start = addon.BlenderMCPServer.start
    addon.BlenderMCPServer.start = lambda self: None
    try:
        addon.register()
    finally:
        addon.BlenderMCPServer.start = original_start
    scene = bpy.context.scene
    scene.blendermcp_auto_start_server = False
    for name in FLAGS:
        setattr(scene, name, False)
    for name in CREDENTIALS:
        setattr(scene, name, "")
    for entry in bpy.context.preferences.addons.values():
        preferences = entry.preferences
        for name in ("hyper3d_api_key", "sketchfab_api_key", "hunyuan3d_secret_id",
                     "hunyuan3d_secret_key", "hunyuan3d_api_url"):
            if hasattr(preferences, name):
                setattr(preferences, name, "")
    scene["vrm_session"] = session["session"]
    scene.blendermcp_port = session["port"]
    server = addon.BlenderMCPServer(host="127.0.0.1", port=session["port"])
    bpy.types.blendermcp_server = server
    server.start()
    scene.blendermcp_server_running = server.running
    if not server.running or server.socket.getsockname() != ("127.0.0.1", session["port"]):
        raise RuntimeError("Owned native listener did not start successfully")
    return server


def run(session_file: Path) -> None:
    """Readmit sources/binary, import the addon once, and publish startup identity."""
    global DENIAL_LOG
    session = json.loads(session_file.read_text())
    root = Path(session["source_root"])
    data = admit_sources(root, Path(session["manifest"]), session["manifest_sha256"])
    if session["binary_sha256"] != data["selected_blender"]["sha256"]:
        raise ValueError("Native binary hash differs from the admitted descriptor selection")
    admit_binary(Path(session["binary"]), session["binary_sha256"])
    DENIAL_LOG = Path(session["output"]) / "requests-denied.jsonl"
    with DENIAL_LOG.open("x"):
        pass
    import bpy
    import requests

    requests.Session.send = deny_requests
    if Path(bpy.app.binary_path).resolve() != Path(session["binary"]):
        raise ValueError("Startup is running inside an unselected Blender executable")
    spec = importlib.util.spec_from_file_location("vrm_owned_blender_addon",
                                                root / PACKAGE / "vendor/addon.py")
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    initialize(addon, bpy, requests, session)
    identity = expected_identity(session, os.getpid())
    scene = bpy.context.scene
    identity.update(port=scene.blendermcp_port,
                    disabled=all(not getattr(scene, name) for name in FLAGS),
                    credentials_blank=all(not getattr(scene, name) for name in CREDENTIALS))
    receipt = Path(session["output"]) / "ready.json"
    pending = receipt.with_suffix(".pending")
    pending.write_text(json.dumps(identity))
    pending.replace(receipt)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-file", type=Path, required=True)
    try:
        run(parser.parse_args(sys.argv[sys.argv.index("--") + 1:]).session_file)
    except Exception:
        import traceback
        traceback.print_exc()
        os._exit(2)
