#!/usr/bin/env python3
"""Preview or execute the frozen one-shot no-communication prompt-D validation.

There is deliberately no resume mode: an interrupted assignment cannot be silently
retried. Docker execution must use the repository's remote-Docker wrapper.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

from messageboardbench.calibration_run import (
    prepare_validation_samples, read_frozen_manifest, read_validation_audit,
)


ROOT = Path(__file__).resolve().parents[1]
REMOTE_DOCKER_HOST = "ssh://pj@100.68.126.75"
LEDGER_DIR = ROOT / "work" / "prompt-validation-consumption"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--validation-audit", type=Path, required=True)
    p.add_argument("--execute", action="store_true")
    return p


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")


def budget() -> dict:
    import httpx
    response = httpx.get(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()["data"]
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            **{key: data.get(key) for key in ("usage", "limit", "limit_remaining")}}


def consume_once(manifest: dict, manifest_path: Path, out: Path) -> dict:
    """Atomically prevent selecting among repeated validation executions."""
    plan_hash = manifest["manifest_sha256"]
    receipt_path = LEDGER_DIR / f"{plan_hash}.json"
    receipt = {
        "schema_version": 1,
        "status": "consumed",
        "purpose": "one-shot-prompt-d-validation",
        "calibration_plan_path": str(manifest_path.resolve()),
        "calibration_plan_file_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "calibration_plan_sha256": plan_hash,
        "output_directory": str(out.resolve()),
        "consumed_at": datetime.now(timezone.utc).isoformat(),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with receipt_path.open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except FileExistsError as exc:
        raise ValueError(f"prompt-D validation plan was already consumed: {receipt_path}") from exc
    return {**receipt, "receipt_path": str(receipt_path.resolve())}


def assert_unconsumed(manifest: dict) -> None:
    receipt_path = LEDGER_DIR / f"{manifest['manifest_sha256']}.json"
    if receipt_path.exists():
        raise ValueError(f"prompt-D validation plan was already consumed: {receipt_path}")


def _result_row(log: object, assignment: dict, completion: dict) -> dict:
    rows = []
    for sample in log.samples or []:
        score = next(iter(sample.scores.values())) if sample.scores else None
        rows.append({
            "assignment": assignment, "log": log.location, "sample_id": str(sample.id),
            "score": score.value if score else None, "messages": len(sample.messages),
            "model_calls": sum(message.role == "assistant" for message in sample.messages),
            "tool_calls": sum(len(getattr(message, "tool_calls", []) or []) for message in sample.messages),
            "usage": {key: value.model_dump(mode="json") for key, value in sample.model_usage.items()},
            "limit": sample.limit.model_dump(mode="json") if sample.limit else None,
            "error": sample.error.message if sample.error else None,
            "unsuccessful_completion": sample.metadata.get("unsuccessful_completion"),
            "plain_text_completion": sample.metadata.get("plain_text_completion"),
            "calibration": sample.metadata.get("calibration"), "completion": completion,
            "scratch_files": list((score.metadata or {}).get("scratch_files", {})) if score else [],
            "test_modified_ever": (score.metadata or {}).get("test_modified_ever") if score else None,
            "manual_behavior_review": "pending",
        })
    if len(rows) != 1:
        raise RuntimeError("each validation assignment must return exactly one sample")
    return rows[0]


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    manifest, source = read_frozen_manifest(args.manifest)
    assignments = manifest["validation_assignments"]
    if any(row["prompt_variant"] != "D" for row in assignments):
        raise ValueError("validation runner accepts only frozen prompt-D assignments")
    validation_ids = set(manifest["task_partitions"]["validation"])
    forbidden = (set(manifest["task_partitions"]["development"])
                 | set(manifest["task_partitions"]["communication_holdout"]))
    if any(row["task_id"] not in validation_ids or row["task_id"] in forbidden
           for row in assignments):
        raise ValueError("validation runner refuses development or communication-holdout tasks")
    environment = manifest["environment"]
    audit, audit_source = read_validation_audit(args.validation_audit, manifest)
    out = args.out.resolve()
    preview = {
        "purpose": "prompt-calibration-validation-execution", "phase": "validation",
        "execute": args.execute, "manifest": source,
        "dataset": {"path": manifest["benchmark"]["dataset"],
                    "revision": manifest["benchmark"]["dataset_revision"],
                    "revision_kind": "immutable_commit"},
        "model": environment["model"], "assignments": len(assignments),
        "communication": "none", "validation_assignments_executed": args.execute,
        "development_assignments_executed": False,
        "communication_holdout_assignments_executed": False, "output": str(out),
    }
    print(json.dumps(preview, indent=2), flush=True)
    if not args.execute:
        print("Preview only; no dataset, Docker container, model request, ledger, or output was created.")
        return 0
    if os.environ.get("DOCKER_HOST") != REMOTE_DOCKER_HOST:
        raise RuntimeError(
            "Execution requires the remote Docker daemon; use `just prompt-validation-run ...`"
        )
    assert_unconsumed(manifest)

    os.chdir(ROOT)
    from dotenv import load_dotenv
    from inspect_ai import Task, eval as inspect_eval
    from messageboardbench.board_task import episode_solver
    from messageboardbench.task import scratch_scorer
    import impossiblebench.livecodebench_agent_full as upstream_agent
    import impossiblebench.livecodebench_scorers as upstream_scorer
    import impossiblebench.livecodebench_tasks as upstream_tasks

    prepared = prepare_validation_samples(manifest, source)
    if len(prepared) != len(assignments):
        raise RuntimeError("prepared samples do not match frozen validation assignments")
    audited = {(row["task_id"], row["split"]): row for row in audit["approved_pairs"]}
    for item in prepared:
        assignment, metadata = item["assignment"], item["sample"].metadata
        row = audited[(assignment["task_id"], assignment["split"])]
        for field, metadata_field in (("task_prompt_sha256", "prompt"), ("test_sha256", "test")):
            value = metadata.get(metadata_field)
            if not isinstance(value, str) or hashlib.sha256(value.encode()).hexdigest() != row[field]:
                raise ValueError(f"validation audit byte mismatch for {assignment['split']}/{assignment['task_id']}")
    load_dotenv(ROOT / ".env")
    out.mkdir(parents=True, exist_ok=False)
    consumption = consume_once(manifest, args.manifest, out)
    before = budget()
    if before["limit_remaining"] is None or before["limit_remaining"] <= 0:
        raise RuntimeError("OpenRouter key has no remaining budget; cap was not changed")
    run_manifest = {
        **preview, "execute": True, "output": str(out),
        "message_limit": environment["message_limit"], "token_limit": environment["token_limit"],
        "time_limit_seconds": environment["time_limit_seconds"],
        "temperature": environment["temperature"], "reasoning_effort": environment["reasoning_effort"],
        "max_attempts": environment["max_attempts"], "completion": environment["completion_policy"],
        "strict_tools": environment["strict_tools"], "sample_retries": environment["sample_retries"],
        "request_retries": environment["request_retries"],
        "assignment_execution": "sequential in frozen validation assignment_index order",
        "validation_audit": audit_source,
        "validation_plan_consumption": consumption,
    }
    shutil.copyfile(args.manifest, out / "frozen-plan.json")
    dump(out / "run-manifest.json", run_manifest)
    dump(out / "budget-before.json", before)
    snapshot = out / "source-snapshot"
    snapshot.mkdir()
    sources = [Path(__file__), *(sorted((ROOT / "src/messageboardbench").glob("*.py"))),
               Path(upstream_agent.__file__), Path(upstream_scorer.__file__),
               Path(upstream_tasks.__file__), ROOT / "compose.yaml"]
    index = []
    for position, source_path in enumerate(sources):
        raw = source_path.read_bytes()
        archived = f"{position}-{source_path.name}"
        (snapshot / archived).write_bytes(raw)
        index.append({"source": str(source_path), "archived": archived,
                      "sha256": hashlib.sha256(raw).hexdigest()})
    dump(snapshot / "index.json", index)
    results = []
    status = {"status": "running", "phase": "validation",
              "completed_assignments": 0, "in_flight_assignment": None}
    try:
        for item in prepared:
            assignment, sample = item["assignment"], item["sample"]
            assignment_index = assignment["assignment_index"]
            episode_id = f"validation-{manifest['manifest_sha256'][:10]}-{assignment_index:04d}"
            sample.metadata = dict(sample.metadata or {})
            sample.metadata["episode_id"] = episode_id
            sample.metadata["calibration"]["episode_id"] = episode_id
            dump(out / f"assignment-{assignment_index:04d}-input.json", {
                "assignment": assignment, "sample": sample.model_dump(mode="json"),
                "provenance": sample.metadata["calibration"],
            })
            task = Task(
                name=f"prompt_d_validation_{assignment_index:04d}", dataset=[sample],
                solver=episode_solver("private", episode_id, assignment["task_id"], "no-board",
                                      completion_mode="plain-final"),
                scorer=scratch_scorer(assignment["split"]),
                sandbox=("docker", str(ROOT / "compose.yaml")),
                message_limit=environment["message_limit"],
                metadata={**run_manifest, "assignment": assignment, "split": assignment["split"],
                          "prompt_variant": "D", "episode_id": episode_id},
            )
            status["in_flight_assignment"] = assignment_index
            dump(out / "status.json", status)
            logs = inspect_eval(
                [task], model=environment["model"], model_args={"strict_tools": environment["strict_tools"]},
                log_dir=str(out / "evals"), max_tasks=1, max_samples=1, max_sandboxes=1,
                max_connections=1, max_retries=environment["request_retries"], timeout=300,
                retry_on_error=environment["sample_retries"], fail_on_error=False,
                time_limit=environment["time_limit_seconds"], token_limit=environment["token_limit"],
                temperature=environment["temperature"], reasoning_effort=environment["reasoning_effort"],
            )
            if len(logs) != 1:
                raise RuntimeError("each validation assignment must return exactly one log")
            row = _result_row(logs[0], assignment, environment["completion_policy"])
            results.append(row)
            dump(out / "results.json", results)
            if row["error"] or logs[0].status != "success":
                raise RuntimeError(f"validation assignment {assignment_index} was incomplete")
            status.update(completed_assignments=assignment_index, in_flight_assignment=None)
            dump(out / "status.json", status)
        status["status"] = "completed"
        return 0
    except BaseException as exc:
        status.update(status="interrupted", error=repr(exc))
        raise
    finally:
        dump(out / "status.json", status)
        try:
            after = budget()
            after["usage_delta"] = after["usage"] - before["usage"]
        except Exception as accounting_error:
            after = {"accounting_error": repr(accounting_error), "usage_delta": None}
        dump(out / "budget-after.json", after)


if __name__ == "__main__":
    raise SystemExit(main())
