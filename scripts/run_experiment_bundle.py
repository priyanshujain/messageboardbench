"""Validate and run one frozen unattended experiment bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from messageboardbench.experiment_bundle import load_and_validate, run_bundle


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    bundle = args.bundle if args.bundle.is_absolute() else ROOT / args.bundle
    manifest_path = bundle / "experiment.json"
    try:
        manifest, _ = load_and_validate(manifest_path, ROOT)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if args.validate_only:
        print(f"Ready: {manifest['experiment_id']} ({manifest['manifest_sha256']})")
        return 0
    return run_bundle(manifest_path, ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
