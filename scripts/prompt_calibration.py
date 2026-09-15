"""Preview or freeze a no-communication ImpossibleBench prompt-calibration plan.

This command never calls a model and never starts Docker.  It records a design that a
separate runner may execute later with explicit authorization.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from messageboardbench.prompt_calibration import (
    DEFAULT_PARTITIONS,
    VARIANTS_BY_ID,
    TaskPartitions,
    build_manifest,
    write_manifest,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset-revision", required=True, help="Pinned dataset commit/revision")
    p.add_argument("--variants", nargs="+", choices=tuple(VARIANTS_BY_ID),
                   default=list(VARIANTS_BY_ID))
    p.add_argument("--development-ids", nargs="+", default=list(DEFAULT_PARTITIONS.development))
    p.add_argument("--validation-ids", nargs="+", default=list(DEFAULT_PARTITIONS.validation))
    p.add_argument("--communication-holdout-ids", nargs="+",
                   default=list(DEFAULT_PARTITIONS.communication_holdout))
    p.add_argument("--replicates", type=int, default=1)
    p.add_argument("--seed", type=int, default=909)
    p.add_argument("--model", default="openrouter/z-ai/glm-5.3-flash")
    p.add_argument("--messages", type=int, default=90)
    p.add_argument("--tokens", type=int, default=1_000_000)
    p.add_argument("--sample-seconds", type=int, default=1_800)
    p.add_argument("--temperature", type=float, default=1)
    p.add_argument("--reasoning-effort",
                   choices=("none", "minimal", "low", "medium", "high", "xhigh"),
                   default="high")
    p.add_argument("--out", type=Path, help="Fresh manifest path; omit for preview only")
    return p


def configuration(args: argparse.Namespace) -> dict:
    partitions = TaskPartitions(
        tuple(args.development_ids),
        tuple(args.validation_ids),
        tuple(args.communication_holdout_ids),
    )
    return build_manifest(
        partitions=partitions,
        variant_ids=tuple(args.variants),
        replicates=args.replicates,
        seed=args.seed,
        model=args.model,
        dataset_revision=args.dataset_revision,
        message_limit=args.messages,
        token_limit=args.tokens,
        time_limit=args.sample_seconds,
        temperature=args.temperature,
        reasoning_effort=args.reasoning_effort,
    )


def main() -> None:
    args = parser().parse_args()
    manifest = configuration(args)
    print(json.dumps(manifest, indent=2))
    if args.out is None:
        print("Preview only; no file, Docker container, or model request was created.")
        return
    write_manifest(args.out, manifest)
    print(f"Wrote frozen calibration plan to {args.out}")


if __name__ == "__main__":
    main()
