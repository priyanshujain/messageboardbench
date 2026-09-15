#!/usr/bin/env python3
"""Verify completed calibration evidence and optionally write a review template."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from messageboardbench.confirmation import (
    calibration_review_template,
    prompt_d_validation_review_template,
    verify_completed_calibration,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--review-template", type=Path)
    parser.add_argument("--validation-run", type=Path)
    parser.add_argument("--validation-review-template", type=Path)
    args = parser.parse_args(argv)
    evidence = verify_completed_calibration(args.plan, args.run)
    if args.review_template:
        template = calibration_review_template(evidence)
        args.review_template.parent.mkdir(parents=True, exist_ok=True)
        with args.review_template.open("x", encoding="utf-8") as handle:
            json.dump(template, handle, indent=2, sort_keys=True)
            handle.write("\n")
    if bool(args.validation_run) != bool(args.validation_review_template):
        parser.error("--validation-run and --validation-review-template must be used together")
    if args.validation_run:
        template = prompt_d_validation_review_template(
            args.plan, args.validation_run,
            calibration_evidence_sha256=evidence["evidence_sha256"],
        )
        args.validation_review_template.parent.mkdir(parents=True, exist_ok=True)
        with args.validation_review_template.open("x", encoding="utf-8") as handle:
            json.dump(template, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
