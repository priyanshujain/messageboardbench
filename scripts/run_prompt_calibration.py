#!/usr/bin/env python3
"""Preview or execute a frozen no-communication A-D or adaptive-E calibration.

Execution is paid and requires --execute. Docker execution must be routed through
the repository's remote-Docker wrapper; source, Python, logs, and credentials remain
local. Communication-holdout and validation assignments are never run here.
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
    prepare_development_samples,
    read_frozen_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
REMOTE_DOCKER_HOST = "ssh://pj@100.68.126.75"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--resume", action="store_true",
                   help="continue a safely interrupted output at an assignment boundary")
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
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        **{key: data.get(key) for key in ("usage", "limit", "limit_remaining")},
    }


def _result_row(log: object, assignment: dict, completion: dict) -> dict:
    rows = []
    for sample in log.samples or []:
        score = next(iter(sample.scores.values())) if sample.scores else None
        rows.append({
            "assignment": assignment,
            "log": log.location,
            "sample_id": str(sample.id),
            "score": score.value if score else None,
            "messages": len(sample.messages),
            "model_calls": sum(message.role == "assistant" for message in sample.messages),
            "tool_calls": sum(len(getattr(message, "tool_calls", []) or []) for message in sample.messages),
            "usage": {key: value.model_dump(mode="json") for key, value in sample.model_usage.items()},
            "limit": sample.limit.model_dump(mode="json") if sample.limit else None,
            "error": sample.error.message if sample.error else None,
            "unsuccessful_completion": sample.metadata.get("unsuccessful_completion"),
            "plain_text_completion": sample.metadata.get("plain_text_completion"),
            "completion_edge_events": sample.metadata.get("completion_edge_events", []),
            "calibration": sample.metadata.get("calibration"),
            "completion": completion,
            "scratch_files": list((score.metadata or {}).get("scratch_files", {})) if score else [],
            "test_modified_ever": (score.metadata or {}).get("test_modified_ever") if score else None,
            "manual_behavior_review": "pending",
        })
    if len(rows) != 1:
        raise RuntimeError("each calibration assignment must return exactly one sample")
    return rows[0]


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.resume and not args.execute:
        parser().error("--resume requires --execute")
    manifest_header = json.loads(args.manifest.read_bytes())
    if manifest_header.get("purpose") == "prompt-e-adaptive-calibration-development-only":
        from messageboardbench.prompt_e_calibration import (
            prepare_development_samples as prepare_prompt_e_samples,
            read_frozen_manifest as read_prompt_e_manifest,
        )
        manifest_reader = read_prompt_e_manifest
        sample_preparer = prepare_prompt_e_samples
        execution_purpose = "prompt-e-adaptive-calibration-execution"
        completion_mode = "neutral-edge-v2"
        episode_prefix = "prompt-e"
    else:
        manifest_reader = read_frozen_manifest
        sample_preparer = prepare_development_samples
        execution_purpose = "prompt-calibration-development-execution"
        completion_mode = "plain-final"
        episode_prefix = "calibration"
    manifest, source = manifest_reader(args.manifest)
    out = args.out.resolve()
    environment = manifest["environment"]
    preview = {
        "purpose": execution_purpose,
        "phase": "development",
        "execute": args.execute,
        "resume": args.resume,
        "manifest": source,
        "dataset": {
            "path": manifest["benchmark"]["dataset"],
            "revision": manifest["benchmark"]["dataset_revision"],
            "revision_kind": "immutable_commit",
        },
        "model": environment["model"],
        "assignments": len(manifest["development_assignments"]),
        "communication": "none",
        "validation_assignments_executed": False,
        "communication_holdout_assignments_executed": False,
        "output": str(out),
    }
    print(json.dumps(preview, indent=2), flush=True)
    if not args.execute:
        print("Preview only; no dataset, Docker container, model request, or output directory was created.")
        return 0
    if os.environ.get("DOCKER_HOST") != REMOTE_DOCKER_HOST:
        run_recipe = (
            "prompt-e-run"
            if completion_mode == "neutral-edge-v2"
            else "prompt-calibration-run"
        )
        raise RuntimeError(
            "Execution requires DOCKER_HOST=ssh://pj@100.68.126.75; "
            f"use `just {run_recipe} ...` so only the remote Docker daemon is used"
        )

    os.chdir(ROOT)
    from dotenv import load_dotenv
    from inspect_ai import Task, eval as inspect_eval
    from messageboardbench.board_task import episode_solver
    from messageboardbench.task import scratch_scorer
    import impossiblebench.livecodebench_agent_full as upstream_agent
    import impossiblebench.livecodebench_scorers as upstream_scorer
    import impossiblebench.livecodebench_tasks as upstream_tasks

    prepared = sample_preparer(manifest, source)
    if len(prepared) != len(manifest["development_assignments"]):
        raise RuntimeError("prepared samples do not match the frozen assignment count")
    load_dotenv(ROOT / ".env")
    before = budget()
    if before["limit_remaining"] is None or before["limit_remaining"] <= 0:
        raise RuntimeError("OpenRouter key has no remaining budget; cap was not changed")

    run_manifest = {
        **preview,
        "execute": True,
        "output": str(out),
        "message_limit": environment["message_limit"],
        "token_limit": environment["token_limit"],
        "time_limit_seconds": environment["time_limit_seconds"],
        "temperature": environment["temperature"],
        "reasoning_effort": environment["reasoning_effort"],
        "max_attempts": environment["max_attempts"],
        "completion": environment["completion_policy"],
        "strict_tools": environment["strict_tools"],
        "sample_retries": environment["sample_retries"],
        "request_retries": environment["request_retries"],
        "assignment_execution": "sequential in frozen assignment_index order",
    }
    if args.resume:
        if not out.is_dir():
            raise ValueError("--resume requires an existing output directory")
        frozen = out / "frozen-plan.json"
        if not frozen.is_file() or frozen.read_bytes() != Path(source["path"]).read_bytes():
            raise ValueError("resume manifest bytes differ from the frozen run plan")
        existing_run_manifest = json.loads((out / "run-manifest.json").read_text())
        if existing_run_manifest.get("manifest") != source:
            raise ValueError("resume run provenance differs from the supplied manifest")
        run_manifest = existing_run_manifest
        status = json.loads((out / "status.json").read_text())
        if status.get("status") != "interrupted" or status.get("phase") != "development":
            raise ValueError("only an interrupted development run can be resumed")
        if status.get("in_flight_assignment") is not None:
            raise ValueError(
                "run stopped during an assignment; refusing an implicit sample retry"
            )
        results_path = out / "results.json"
        results = json.loads(results_path.read_text()) if results_path.exists() else []
        completed = status.get("completed_assignments")
        if not isinstance(completed, int) or completed != len(results):
            raise ValueError("resume status and result count disagree")
        expected_prefix = manifest["development_assignments"][:completed]
        if [row.get("assignment") for row in results] != expected_prefix:
            raise ValueError("resume results are not the exact frozen assignment prefix")
        if any(row.get("error") for row in results):
            raise ValueError("cannot resume a prefix containing sample errors")
        status.update(status="running", resumed_at=datetime.now(timezone.utc).isoformat())
        dump(out / "status.json", status)
        dump(out / f"budget-resume-{len(results) + 1:04d}.json", before)
        accounting_baseline = json.loads((out / "budget-before.json").read_text())
    else:
        out.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(Path(source["path"]), out / "frozen-plan.json")
        dump(out / "run-manifest.json", run_manifest)
        dump(out / "budget-before.json", before)
        snapshot = out / "source-snapshot"
        snapshot.mkdir()
        sources = [
            Path(__file__),
            *(sorted((ROOT / "src/messageboardbench").glob("*.py"))),
            Path(upstream_agent.__file__),
            Path(upstream_scorer.__file__),
            Path(upstream_tasks.__file__),
            ROOT / "compose.yaml",
        ]
        index = []
        for position, source_path in enumerate(sources):
            raw = source_path.read_bytes()
            archived = f"{position}-{source_path.name}"
            (snapshot / archived).write_bytes(raw)
            index.append({
                "source": str(source_path),
                "archived": archived,
                "sha256": hashlib.sha256(raw).hexdigest(),
            })
        dump(snapshot / "index.json", index)
        results = []
        status = {
            "status": "running", "phase": "development",
            "completed_assignments": 0, "in_flight_assignment": None,
        }
        accounting_baseline = before
    try:
        for item in prepared[len(results):]:
            assignment = item["assignment"]
            sample = item["sample"]
            assignment_index = assignment["assignment_index"]
            episode_id = f"{episode_prefix}-{manifest['manifest_sha256'][:10]}-{assignment_index:04d}"
            sample.metadata = dict(sample.metadata or {})
            sample.metadata["episode_id"] = episode_id
            sample.metadata["calibration"]["episode_id"] = episode_id
            dump(out / f"assignment-{assignment_index:04d}-input.json", {
                "assignment": assignment,
                "sample": sample.model_dump(mode="json"),
                "provenance": sample.metadata["calibration"],
            })
            task = Task(
                name=f"{episode_prefix.replace('-', '_')}_development_{assignment_index:04d}",
                dataset=[sample],
                solver=episode_solver(
                    "private", episode_id, assignment["task_id"], "no-board",
                    completion_mode=completion_mode,
                ),
                scorer=scratch_scorer(assignment["split"]),
                sandbox=("docker", str(ROOT / "compose.yaml")),
                message_limit=environment["message_limit"],
                metadata={
                    **run_manifest,
                    "assignment": assignment,
                    "split": assignment["split"],
                    "prompt_variant": assignment["prompt_variant"],
                    "episode_id": episode_id,
                },
            )
            print(f"Starting development assignment {assignment_index}/{len(prepared)}", flush=True)
            status["in_flight_assignment"] = assignment_index
            dump(out / "status.json", status)
            logs = inspect_eval(
                [task],
                model=environment["model"],
                model_args={"strict_tools": environment["strict_tools"]},
                log_dir=str(out / "evals"),
                max_tasks=1,
                max_samples=1,
                max_sandboxes=1,
                max_connections=1,
                max_retries=environment["request_retries"],
                timeout=300,
                retry_on_error=environment["sample_retries"],
                fail_on_error=False,
                time_limit=environment["time_limit_seconds"],
                token_limit=environment["token_limit"],
                temperature=environment["temperature"],
                reasoning_effort=environment["reasoning_effort"],
            )
            if len(logs) != 1:
                raise RuntimeError("each calibration assignment must return exactly one log")
            row = _result_row(logs[0], assignment, environment["completion_policy"])
            results.append(row)
            dump(out / "results.json", results)
            if row["error"] or logs[0].status != "success":
                raise RuntimeError(f"calibration assignment {assignment_index} was incomplete")
            status["completed_assignments"] = assignment_index
            status["in_flight_assignment"] = None
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
            after["usage_delta"] = after["usage"] - accounting_baseline["usage"]
        except Exception as accounting_error:
            after = {"accounting_error": repr(accounting_error), "usage_delta": None}
        dump(out / "budget-after.json", after)


if __name__ == "__main__":
    raise SystemExit(main())
