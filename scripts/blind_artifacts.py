#!/usr/bin/env python3
"""Generate, freeze, or unblind confirmatory artifact-review packets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from messageboardbench.blinded_review import freeze_labels, generate_packets, join_labels


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--report", type=Path, required=True)
    generate.add_argument("--packets", type=Path, required=True)
    generate.add_argument("--mapping", type=Path, required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--labels", type=Path, required=True)
    freeze.add_argument("--mapping", type=Path, required=True)
    freeze.add_argument("--out", type=Path, required=True)
    join = sub.add_parser("join")
    join.add_argument("--frozen-labels", type=Path, required=True)
    join.add_argument("--mapping", type=Path, required=True)
    join.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "generate":
        result = generate_packets(args.report, args.packets, args.mapping)
    elif args.command == "freeze":
        result = freeze_labels(args.labels, args.mapping, args.out)
    else:
        result = join_labels(args.frozen_labels, args.mapping, args.out)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
