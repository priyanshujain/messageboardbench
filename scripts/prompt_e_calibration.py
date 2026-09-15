#!/usr/bin/env python3
"""Preview or freeze the separate 24-episode adaptive prompt-E plan.

This command never loads a dataset, starts Docker, or calls a model.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from messageboardbench.prompt_e_calibration import build_manifest, write_manifest


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--dataset-revision", required=True)
    value.add_argument("--seed", type=int, default=1919)
    value.add_argument("--model", default="openrouter/z-ai/glm-5.3-flash")
    value.add_argument("--messages", type=int, default=90)
    value.add_argument("--tokens", type=int, default=1_000_000)
    value.add_argument("--sample-seconds", type=int, default=1_800)
    value.add_argument("--temperature", type=float, default=1)
    value.add_argument("--reasoning-effort",
                       choices=("none", "minimal", "low", "medium", "high", "xhigh"),
                       default="high")
    value.add_argument("--out", type=Path)
    return value


def configuration(args: argparse.Namespace) -> dict:
    return build_manifest(
        dataset_revision=args.dataset_revision,
        seed=args.seed,
        model=args.model,
        message_limit=args.messages,
        token_limit=args.tokens,
        time_limit_seconds=args.sample_seconds,
        temperature=args.temperature,
        reasoning_effort=args.reasoning_effort,
    )


def main() -> None:
    args = parser().parse_args()
    manifest = configuration(args)
    print(json.dumps(manifest, indent=2))
    if args.out is None:
        print("Preview only; no file, dataset, Docker container, or model request was created.")
        return
    write_manifest(args.out, manifest)
    print(f"Wrote frozen prompt-E calibration plan to {args.out}")


if __name__ == "__main__":
    main()
