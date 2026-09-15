"""Preview or execute at most eight paid diagnostic samples; never change key limits.

Run from the repository root. Preview is the default; --execute starts the eval.
Use a NEW output directory for a changed configuration. Identical invocations resume
through Inspect eval_set. These are development runs, not confirmatory results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--split", choices=["original", "conflicting"], default="conflicting")
    p.add_argument("--ids", nargs="+", default=["lcbhard_0", "lcbhard_1"])
    p.add_argument("--model", default="openrouter/z-ai/glm-5.3-flash")
    p.add_argument("--messages", type=int, choices=[30, 60], default=30)
    p.add_argument("--sample-seconds", type=int, default=1200)
    p.add_argument("--tokens", type=int, default=200000,
                   help="Per-sample total token limit, including repeated input; not a dollar cap")
    p.add_argument("--seed-file", type=Path, action="append", default=[])
    p.add_argument("--exposure", choices=["available", "inspect"], default="available")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--execute", action="store_true")
    return p


def configuration(args: argparse.Namespace) -> tuple[dict, dict[str, str]]:
    import messageboardbench.task as task_module
    import impossiblebench.livecodebench_scorers as upstream_scorer
    from messageboardbench.task import validate_seed_files
    if not 1 <= len(args.ids) <= 8 or len(set(args.ids)) != len(args.ids):
        raise ValueError("Choose 1–8 distinct sample IDs for diagnostics")
    if not 1 <= args.sample_seconds <= 1800 or not 1 <= args.tokens <= 400000:
        raise ValueError("Diagnostics require 1–1800 seconds and 1–400000 tokens per sample")
    seeds = {p.name: p.read_text() for p in args.seed_file}
    if len(seeds) != len(args.seed_file):
        raise ValueError("Seed filenames must be unique")
    validate_seed_files(seeds)
    config = {
        "purpose": "development-only", "split": args.split, "ids": args.ids,
        "model": args.model, "message_limit": args.messages,
        "time_limit": args.sample_seconds, "token_limit": args.tokens,
        "exposure": args.exposure, "max_attempts": 3, "concurrency": 2,
        "timeout": 300, "max_retries": 1, "retry_attempts": 1,
        "source_sha256": {str(Path(p).resolve()): hashlib.sha256(Path(p).read_bytes()).hexdigest()
                          for p in (__file__, task_module.__file__, upstream_scorer.__file__)},
        "seed_files": {p.name: {"source": str(p.resolve()),
            "sha256": hashlib.sha256(seeds[p.name].encode()).hexdigest()}
            for p in args.seed_file},
    }
    return config, seeds


def main() -> None:
    args = parser().parse_args()
    config, seeds = configuration(args)
    print(json.dumps(config, indent=2))
    if not args.execute:
        print("Preview only. Add --execute to run; no model request has been sent.")
        return
    # Refuse before loading credentials or making a model request if Docker is down.
    subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], check=True,
                   timeout=15, capture_output=True)
    from dotenv import load_dotenv
    from inspect_ai import eval_set
    from messageboardbench.analysis import rows, summarise, write_csv
    from messageboardbench.task import scratch_livecodebench

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = args.out / "manifest.json"
    if manifest.exists() and json.loads(manifest.read_text()) != config:
        raise ValueError("Configuration changed; use a new --out directory")
    manifest.write_text(json.dumps(config, indent=2) + "\n")
    load_dotenv()
    task = scratch_livecodebench(split=args.split, message_limit=args.messages,
                                seed_files=seeds, exposure=args.exposure)
    missing = set(args.ids) - {str(sample.id) for sample in task.dataset}
    if missing:
        raise ValueError(f"Unknown task IDs: {sorted(missing)}")
    success, logs = eval_set(
        task,
        log_dir=str(args.out / "evals"), model=args.model, sample_id=args.ids,
        max_connections=2, max_sandboxes=2, max_samples=2,
        max_retries=1, retry_attempts=1, timeout=300,
        time_limit=args.sample_seconds, token_limit=args.tokens,
        fail_on_error=False,
    )
    table = rows(s for log in logs for s in (log.samples or []))
    write_csv(table, args.out / "samples.csv")
    summary = {"eval_set_success": success, **summarise(table)}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
