"""Launch spatial_session only after admission by a trusted Python with -I -S -B.

This admission boundary assumes trusted owned scripts and a trusted descriptor
digest supplied separately by the coordinator. It is not a host sandbox.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import spatial_session as session  # noqa: E402
from spatial_runtime import CLEARANCE, admit_runtime  # noqa: E402


def main(argv=None) -> int:
    """Refuse before execution, or replace this launcher with the admitted session."""
    args = session.arguments(argv)
    try:
        if not sys.flags.isolated or not sys.flags.no_site:
            raise ValueError("Trusted launcher requires -I -S -B")
        data = session.admit_sources(args.source_root.absolute(), args.manifest.absolute(), args.manifest_sha256)
        inputs = session.Inputs(args.inputs.absolute(), args.inputs_sha256)
        if args.output.exists():
            raise ValueError("Owned output must be absent")
        if data.get("runtime_clearance") != CLEARANCE:
            report = {"sources_admitted": True, "inputs_admitted": True,
                      "frames": len(inputs.frames), **session.runtime_report(data)}
            if args.check:
                print(json.dumps(report))
                return 2
            raise ValueError("Runtime grants are blocked")
        runtime = admit_runtime(data)
        command = [runtime["executable"], "-I", "-S", "-B", session.__file__]
        for name in ("source_root", "manifest", "inputs", "output"):
            command.extend(["--" + name.replace("_", "-"), str(getattr(args, name).absolute())])
        command.extend(["--manifest-sha256", args.manifest_sha256, "--inputs-sha256", args.inputs_sha256])
        if args.check:
            command.append("--check")
        allowed = ("HOME", "CODEX_HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE")
        env = {key: os.environ[key] for key in allowed if key in os.environ}
        env["PATH"] = "/usr/bin:/bin"
        os.chdir("/")
        os.execve(runtime["executable"], command, env)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(f"Spatial launch refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
