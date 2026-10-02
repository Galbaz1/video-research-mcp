"""CLI for the installed first-party validate/build/check lesson component."""

import argparse
import asyncio
import json

from video_research_mcp.education import build_lesson, check_lesson, validate_lesson


def parser():
    """Expose exact file identities without provider, renderer or binary override flags."""
    cli = argparse.ArgumentParser(description=__doc__)
    actions = cli.add_subparsers(dest="action", required=True)
    for name in ("validate", "build"):
        command = actions.add_parser(name)
        command.add_argument("--spec", required=True)
        command.add_argument("--spec-sha256", required=True)
        command.add_argument("--audio", required=True)
        command.add_argument("--audio-sha256", required=True)
        command.add_argument("--timeout", type=float, default=120)
        if name == "build":
            command.add_argument("--output", required=True)
    check = actions.add_parser("check")
    check.add_argument("directory")
    check.add_argument("--receipt-sha256", required=True)
    check.add_argument("--timeout", type=float, default=120)
    return cli


async def run(args):
    """Use only the three concrete component entry points."""
    if args.action == "check":
        return await check_lesson(args.directory, args.receipt_sha256, args.timeout)
    values = (args.spec, args.spec_sha256, args.audio, args.audio_sha256)
    if args.action == "validate":
        return await validate_lesson(*values, timeout_seconds=args.timeout)
    return await build_lesson(*values, args.output, timeout_seconds=args.timeout)


def main():
    """Print measured JSON or an explicit terminal refusal; never retry a failed attempt."""
    args = parser().parse_args()
    try:
        result = asyncio.run(run(args))
    except Exception as exc:
        result = {"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)[:512],
                  "attempt_receipt": getattr(exc, "lesson_attempt_path", None)}
        print(json.dumps(result, indent=2, allow_nan=False))
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
