#!/usr/bin/env python3
"""Generate and semantically freeze a model-free LiveCodeBench holdout audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from messageboardbench.holdout_audit import (
    build_candidate,
    candidate_review_template,
    freeze_reviewed_audit,
    resolve_revision,
    validate_revision,
    write_json_new,
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    candidate = sub.add_parser("candidate", help="fetch pinned tasks and run mechanical checks")
    candidate.add_argument("--dataset-revision", type=validate_revision)
    candidate.add_argument(
        "--partition", choices=("communication_holdout", "validation"),
        default="communication_holdout",
    )
    candidate.add_argument("--out", type=Path, required=True)
    candidate.add_argument("--review-template", type=Path, required=True)
    freeze = sub.add_parser("freeze", help="validate a completed semantic review and freeze ready audit")
    freeze.add_argument("--candidate", type=Path, required=True)
    freeze.add_argument("--review", type=Path, required=True)
    freeze.add_argument("--out", type=Path, required=True)
    return root


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if args.command == "candidate":
        revision = args.dataset_revision or resolve_revision()
        from messageboardbench.prompt_calibration import DEFAULT_PARTITIONS
        task_ids = getattr(DEFAULT_PARTITIONS, args.partition)
        candidate = build_candidate(revision, task_ids=task_ids, partition=args.partition)
        # Serialize once so the review template binds to exactly what is written.
        encoded = (json.dumps(candidate, indent=2, sort_keys=True) + "\n").encode()
        if args.out.exists() or args.review_template.exists():
            raise FileExistsError("candidate and review-template outputs must both be new")
        write_json_new(args.out, candidate)
        write_json_new(args.review_template, candidate_review_template(encoded))
        print(json.dumps({
            "status": "needs_semantic_review",
            "dataset_revision": revision,
            "candidate": str(args.out),
            "review_template": str(args.review_template),
        }, indent=2))
        return

    candidate_bytes = args.candidate.read_bytes()
    review = json.loads(args.review.read_bytes())
    ready = freeze_reviewed_audit(candidate_bytes, review)
    write_json_new(args.out, ready)
    print(json.dumps({
        "status": "ready",
        "dataset_revision": ready["dataset"]["revision"],
        "approved_pairs": len(ready["approved_pairs"]),
        "output": str(args.out),
    }, indent=2))


if __name__ == "__main__":
    main()
