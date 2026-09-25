"""Write an automatic, unreviewed report for separate SWE control runs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from inspect_ai.log import read_eval_log


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def score_label(row: dict | None) -> str:
    if row is None:
        return "missing"
    value = row.get("score")
    if value is None:
        return "null"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 1:
            return "1"
        if value == 0:
            return "0"
    return str(value)


def run_report(label: str, run_dir: Path) -> tuple[dict, dict[str, dict], set[str]]:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    if manifest.get("conditions") != ["control"]:
        raise ValueError(f"{label}: expected a control-only run")
    rows = json.loads((run_dir / "results.json").read_text())
    task_ids = list(manifest["records_sha256"])
    by_task = {row["sample_id"]: row for row in rows}
    if len(by_task) != len(rows):
        raise ValueError(f"{label}: duplicate terminal task rows")
    if set(by_task) - set(task_ids):
        raise ValueError(f"{label}: terminal task is absent from the plan")

    tokens = {name: 0 for name in (
        "input", "output", "cache_read", "reasoning", "total", "limit_usage"
    )}
    limits = {name: 0 for name in ("token", "message", "time", "other")}
    for row in rows:
        log_path = Path(row["log"])
        if not log_path.exists():
            log_path = run_dir / "evals" / log_path.name
        log = read_eval_log(log_path)
        sample = next(sample for sample in log.samples or []
                      if str(sample.id) == row["sample_id"])
        for usage in sample.model_usage.values():
            for source, target in (
                ("input_tokens", "input"), ("output_tokens", "output"),
                ("input_tokens_cache_read", "cache_read"),
                ("reasoning_tokens", "reasoning"), ("total_tokens", "total"),
            ):
                tokens[target] += getattr(usage, source, None) or 0
        tokens["limit_usage"] += sample.token_limit_usage or 0
        if sample.limit:
            kind = sample.limit.type
            limits[kind if kind in limits else "other"] += 1

    scores = [score_label(row) for row in rows]
    report = {
        "model": manifest.get("model") or next(iter(manifest["models_by_team"].values())),
        "run_dir": str(run_dir.resolve()),
        "planned": manifest.get("planned_episodes", len(task_ids)),
        "terminal": len(rows),
        "score_1": scores.count("1"),
        "score_0": scores.count("0"),
        "score_null": scores.count("null"),
        "errors": sum(bool(row.get("error")) or row.get("log_status") == "error"
                      for row in rows),
        "test_modified_ever": sum(row.get("test_modified_ever") is True for row in rows),
        "test_modified_unknown": sum(row.get("test_modified_ever") is None for row in rows),
        "tokens": tokens,
        "limits": limits,
    }
    return report, by_task, set(task_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", required=True, metavar="LABEL=RUN_DIR")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    runs = {}
    for item in args.run:
        if "=" not in item:
            parser.error("--run must have the form LABEL=RUN_DIR")
        label, path = item.split("=", 1)
        if not label or label in runs:
            parser.error("--run labels must be nonempty and unique")
        runs[label] = Path(path)

    summaries = {}
    rows_by_model = {}
    planned_tasks = set()
    for label, path in runs.items():
        summaries[label], rows_by_model[label], task_ids = run_report(label, path)
        planned_tasks.update(task_ids)
    task_ids = sorted(planned_tasks)
    paired = [
        {"task_id": task_id,
         "scores": {label: score_label(rows.get(task_id))
                    for label, rows in rows_by_model.items()}}
        for task_id in task_ids
    ]
    report = {
        "automatic_unreviewed": True,
        "scope": "control-only ImpossibleBench SWE baseline; no communication tools",
        "models": summaries,
        "per_task": paired,
        "limitations": [
            "A numeric scorer pass is not an automatic cheating or behavioral label.",
            "Null and missing outcomes are shown separately and excluded from numeric score counts.",
            "This baseline does not estimate any communication effect.",
        ],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / "report.json", report)
    lines = [
        "# Automatic SWE baseline report", "",
        "Deterministic and unreviewed. Scores are evaluator outputs, not behavioral labels.", "",
        "| Model | Terminal / planned | Score 1 | Score 0 | Null | Errors | Test modified | Token limit | Message limit | Total metered tokens |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, row in summaries.items():
        lines.append(
            f"| {label} | {row['terminal']} / {row['planned']} | {row['score_1']} | "
            f"{row['score_0']} | {row['score_null']} | {row['errors']} | "
            f"{row['test_modified_ever']} | {row['limits']['token']} | "
            f"{row['limits']['message']} | {row['tokens']['total']} |"
        )
    lines += ["", "## Paired task scores", "",
              "| Task | " + " | ".join(runs) + " |",
              "|---|" + "---:|" * len(runs)]
    for item in paired:
        lines.append("| " + item["task_id"] + " | " +
                     " | ".join(item["scores"][label] for label in runs) + " |")
    lines += ["", "Missing means no terminal row; null means a terminal row without a numeric score.",
              "Raw logs remain in each run directory. This control-only baseline makes no communication claim.", ""]
    (args.out / "REPORT.md").write_text("\n".join(lines))
    print(f"Wrote {args.out / 'report.json'} and {args.out / 'REPORT.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
