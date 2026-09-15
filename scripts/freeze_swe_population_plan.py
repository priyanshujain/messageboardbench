"""Freeze the all-task ImpossibleBench SWE population schedule; no model calls."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from messageboardbench.swe_board import (
    NO_STOP_PROMPT_POLICY,
    build_population_plan,
    load_records,
    plan_hash,
)
from messageboardbench.board import MESSAGEBOARD_V2_INTERFACE_VERSION
from messageboardbench.swe_validation import DATASET


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--teams", type=int, default=12)
    parser.add_argument("--cohorts", type=int, default=3)
    parser.add_argument("--seed", type=int, default=910)
    parser.add_argument(
        "--sample-size", type=int,
        help="freeze a deterministic pilot subset of this size (default: full split)",
    )
    parser.add_argument(
        "--exclude-plan", type=Path,
        help="exclude the explicitly selected IDs in an earlier frozen pilot plan",
    )
    parser.add_argument(
        "--messageboard-v2", action="store_true",
        help="freeze the send_message/read_messages plus organizer-feedback interface",
    )
    parser.add_argument(
        "--reuse-selection-plan", type=Path,
        help="reuse the exact selected task IDs from an earlier frozen plan",
    )
    parser.add_argument(
        "--no-stop-prompt", action="store_true",
        help="retain DO NOT MODIFY THE TESTS but omit the extra stop/carve-out text",
    )
    args = parser.parse_args()
    if args.messageboard_v2 and args.sample_size is None:
        parser.error("--messageboard-v2 requires --sample-size")
    if args.exclude_plan is not None and args.sample_size is None:
        parser.error("--exclude-plan requires --sample-size")
    if args.reuse_selection_plan is not None and args.sample_size is not None:
        parser.error("--reuse-selection-plan cannot be combined with --sample-size")
    if args.reuse_selection_plan is not None and args.exclude_plan is not None:
        parser.error("--reuse-selection-plan cannot be combined with --exclude-plan")
    if args.no_stop_prompt and not args.messageboard_v2:
        parser.error("--no-stop-prompt requires --messageboard-v2")
    upstream = (ROOT.parent / "impossiblebench").resolve()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=upstream, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    records = load_records(args.revision, "conflicting")
    selected = None
    reused_plan_bytes = None
    reused_plan = None
    if args.reuse_selection_plan is not None:
        reused_plan_bytes = args.reuse_selection_plan.read_bytes()
        reused_plan = json.loads(reused_plan_bytes)
        selected = reused_plan.get("selection", {}).get("instance_ids")
        if (reused_plan.get("status") != "frozen"
                or reused_plan.get("plan_sha256") != plan_hash(reused_plan)
                or reused_plan.get("dataset") != {
                    "path": DATASET, "revision": args.revision, "split": "conflicting",
                }
                or not isinstance(selected, list) or not selected
                or len(selected) != len(set(selected)) or not set(selected) <= set(records)):
            parser.error("--reuse-selection-plan is not a valid matching frozen plan")
    if args.sample_size is not None:
        if not 1 <= args.sample_size <= len(records):
            parser.error("--sample-size must be between 1 and the split size")
        ranked = sorted(
            records,
            key=lambda instance_id: hashlib.sha256(
                f"swe-pilot-selection-v1:{args.seed}:{instance_id}".encode()
            ).digest(),
        )
        excluded: set[str] = set()
        excluded_plan_bytes = None
        if args.exclude_plan is not None:
            excluded_plan_bytes = args.exclude_plan.read_bytes()
            earlier = json.loads(excluded_plan_bytes)
            excluded = set(earlier.get("selection", {}).get("instance_ids", []))
            if (earlier.get("status") != "frozen"
                    or earlier.get("plan_sha256") != plan_hash(earlier)
                    or earlier.get("dataset") != {
                        "path": DATASET,
                        "revision": args.revision,
                        "split": "conflicting",
                    }
                    or earlier.get("seed") != args.seed
                    or not excluded or not excluded <= set(records)):
                parser.error("--exclude-plan does not contain a valid pinned subset")
        selected = [instance_id for instance_id in ranked if instance_id not in excluded][
            :args.sample_size
        ]
        if len(selected) != args.sample_size:
            parser.error("not enough unexcluded records for --sample-size")
    plan = build_population_plan(
        records, revision=args.revision, model=args.model,
        upstream_git_commit=commit, teams=args.teams, cohorts=args.cohorts,
        seed=args.seed, selected_instance_ids=selected,
        tool_interface=(MESSAGEBOARD_V2_INTERFACE_VERSION if args.messageboard_v2 else None),
        prompt_policy=(NO_STOP_PROMPT_POLICY if args.no_stop_prompt else None),
    )
    if selected is not None:
        plan["selection"].update({
            "ranking_namespace": "swe-pilot-selection-v1",
            "ranking_seed": args.seed,
            "excluded_instance_ids": sorted(excluded),
            "excluded_plan": ({
                "path": str(args.exclude_plan),
                "file_sha256": hashlib.sha256(excluded_plan_bytes).hexdigest(),
                "plan_sha256": earlier["plan_sha256"],
            } if args.exclude_plan is not None else None),
        })
        plan["plan_sha256"] = plan_hash(plan)
    if reused_plan is not None:
        plan["selection"].update({
            "kind": "reused_frozen_subset",
            "source_plan": {
                "path": str(args.reuse_selection_plan),
                "file_sha256": hashlib.sha256(reused_plan_bytes).hexdigest(),
                "plan_sha256": reused_plan["plan_sha256"],
            },
        })
        plan["plan_sha256"] = plan_hash(plan)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as handle:
        json.dump(plan, handle, indent=2)
        handle.write("\n")
    print(json.dumps({
        "plan": str(args.out), "instances": len(records),
        "episodes": plan["planned_episodes"], "plan_sha256": plan["plan_sha256"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
