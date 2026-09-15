"""Preview or run the free nochange/oracle SWE-bench readiness matrix."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from messageboardbench.swe_validation import (
    docker_preflight,
    load_pair,
    manifest,
    run_trial,
    validate_expected_matrix,
    validate_semantic_audit,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--revision", required=True, help="full immutable dataset commit SHA")
    p.add_argument("--instance-id", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--execute", action="store_true", help="start four free Docker trials")
    p.add_argument("--audit", type=Path, help="reviewed semantic-audit JSON (required to execute)")
    p.add_argument("--memory", default="8g")
    p.add_argument("--timeout", type=int, default=600)
    return p


def main() -> int:
    args = parser().parse_args()
    original, conflicting = load_pair(args.revision, args.instance_id)
    if not args.execute:
        print(json.dumps(manifest(args.revision, args.instance_id, original, conflicting), indent=2))
        print("Preview only; no container or model request was started.")
        return 0

    if args.audit is None:
        raise SystemExit("--audit is required with --execute; review the same-input contradiction first")
    planned = manifest(args.revision, args.instance_id, original, conflicting)
    validate_semantic_audit(json.loads(args.audit.read_text()), planned)
    docker_preflight(os.environ)
    results = []
    for split, record in (("original", original), ("conflicting", conflicting)):
        for mode in ("nochange", "oracle"):
            results.append(
                run_trial(
                    record,
                    split=split,
                    mode=mode,
                    out_dir=args.out,
                    environ=os.environ,
                    memory=args.memory,
                    timeout_seconds=args.timeout,
                )
            )
    args.out.mkdir(parents=True, exist_ok=True)
    record = manifest(args.revision, args.instance_id, original, conflicting, results)
    validate_expected_matrix(results)
    (args.out / "manifest.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(f"Validated nochange/oracle matrix; outputs are in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
