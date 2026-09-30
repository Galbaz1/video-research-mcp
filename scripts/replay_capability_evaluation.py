"""CLI for offline replay of separately frozen inputs, labels and outputs."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.evaluation.comparison import compare  # noqa: E402
from scripts.evaluation.replay import replay  # noqa: E402
from scripts.evaluation.support import read_json  # noqa: E402


def main() -> None:
    """Score one run and optionally compare an already retained baseline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument(
        "--protocol", type=Path, default=Path("docs/metrics/multimodal-evaluation-protocol.json")
    )
    parser.add_argument("--baseline-outputs", type=Path)
    parser.add_argument("--baseline-receipt", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = replay(args.bundle, args.outputs, args.receipt, args.protocol)
    if bool(args.baseline_outputs) != bool(args.baseline_receipt):
        parser.error("baseline outputs and receipt must be provided together")
    if args.baseline_outputs:
        baseline = replay(args.bundle, args.baseline_outputs, args.baseline_receipt, args.protocol)
        report["comparison"] = compare(report, baseline, read_json(args.protocol))
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Scored {report['summary']['cases']} attempted cases; scope={report['scope']}")


if __name__ == "__main__":
    main()
