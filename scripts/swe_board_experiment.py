"""Run a paired ImpossibleBench SWE control/board population experiment.

Preview is the default. Paid execution requires --execute and the remote Docker
daemon wrapper. Source, logs, credentials, and reports remain on this workstation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from messageboardbench.swe_validation import REMOTE_DOCKER_HOST


ROOT = Path(__file__).resolve().parents[1]
CONDITIONS = ("control", "board")
def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--execute", action="store_true")
    return p


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")


def validate_resume_sources(archive: Path, sources: list[Path]) -> None:
    """Reject resume when archived or current behavioral source bytes changed."""
    index = json.loads((archive / "index.json").read_text())
    current = {str(path.resolve()): path for path in sources}
    if set(current) != {item["source"] for item in index}:
        raise RuntimeError("resume source set differs from frozen source snapshot")
    for item in index:
        archived = archive / item["archived"]
        if hashlib.sha256(archived.read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("resume source snapshot hash mismatch")
        if hashlib.sha256(current[item["source"]].read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("current behavioral source differs from frozen resume snapshot")


def terminal_row(log, evaluated) -> dict:
    final_score = next(iter(evaluated.scores.values())) if evaluated.scores else None
    return {
        "log": log.location, "log_status": log.status,
        "sample_id": str(evaluated.id),
        "condition": evaluated.metadata["condition"], "team": evaluated.metadata["team"],
        "cohort": evaluated.metadata["cohort"], "slot": evaluated.metadata["slot"],
        "episode_id": evaluated.metadata["episode_id"], "split": evaluated.metadata["split"],
        "score": final_score.value if final_score else None,
        "messages": len(evaluated.messages),
        "error": evaluated.error.message if evaluated.error else None,
        "model_patch_captured": (
            isinstance((final_score.metadata or {}).get("model_patch"), str)
            if final_score else False
        ),
        "test_modified_ever": (final_score.metadata or {}).get("test_modified_ever") if final_score else None,
        "manual_behavior_review": "pending",
    }


def sentinel_failed(
    rows: list[dict], *, team: int, condition: str, instance_ids: list[str]
) -> bool:
    """Keep a failed first matched pair blocked across process restarts."""
    expected = {(team, condition, instance_id) for instance_id in instance_ids}
    relevant = {
        (row["team"], row["condition"], row["sample_id"]): row
        for row in rows
        if (row["team"], row["condition"], row["sample_id"]) in expected
    }
    return set(relevant) != expected or any(
        row.get("error")
        or row.get("score") is None
        or row.get("log_status") != "success"
        or not row.get("model_patch_captured")
        for row in relevant.values()
    )


def recover_terminal_rows(out: Path) -> list[dict]:
    """Recover completed/error samples written before a process interruption."""
    from inspect_ai.log import read_eval_log

    rows = []
    for path in sorted((out / "evals").rglob("*.eval")) if (out / "evals").exists() else []:
        log = read_eval_log(path, resolve_attachments=True)
        if log.status not in {"success", "error", "cancelled"}:
            continue
        for sample in log.samples or []:
            if sample.metadata and sample.metadata.get("episode_id"):
                rows.append(terminal_row(log, sample))
    keys = [(row["team"], row["condition"], row["sample_id"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise RuntimeError("duplicate terminal SWE assignments found during resume")
    return rows


def cleanup_matched_images(out: Path, team: int, cohort: int, instance_ids: list[str], records: dict) -> None:
    """Remove only explicit, re-pullable tags after both matched arms terminate."""
    path = out / "image-lifecycle.json"
    lifecycle = json.loads(path.read_text()) if path.exists() else []
    if any(row["team"] == team and row["cohort"] == cohort for row in lifecycle):
        return
    from messageboardbench.swe_validation import swebench_spec

    record = {"team": team, "cohort": cohort, "images": []}
    failed = False
    for instance_id in instance_ids:
        image = swebench_spec(records[instance_id])[0]
        inspected = subprocess.run(
            ["docker", "image", "inspect", image, "--format", "{{json .}}"],
            capture_output=True, text=True, env=os.environ,
        )
        item = {"instance_id": instance_id, "image": image,
                "inspect_returncode": inspected.returncode}
        if inspected.returncode == 0:
            identity = json.loads(inspected.stdout)
            item.update(image_id=identity.get("Id"), repo_digests=identity.get("RepoDigests") or [])
            removed = subprocess.run(
                ["docker", "image", "rm", image], capture_output=True, text=True, env=os.environ,
            )
            item.update(remove_returncode=removed.returncode,
                        remove_output=removed.stdout + removed.stderr)
            failed |= removed.returncode != 0
        else:
            # Already absent is a valid resumed state; it will be pulled if needed.
            item.update(remove_returncode=None, remove_output="image tag already absent")
        record["images"].append(item)
    record["complete"] = not failed
    lifecycle.append(record)
    dump(path, lifecycle)


def account_budget() -> dict:
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


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.execute and os.environ.get("DOCKER_HOST") != REMOTE_DOCKER_HOST:
        raise SystemExit(
            f"execution requires DOCKER_HOST={REMOTE_DOCKER_HOST}; use the remote Docker wrapper"
        )
    from messageboardbench.swe_board import (
        load_records,
        validate_population_plan,
    )
    plan_bytes = args.plan.read_bytes()
    plan = json.loads(plan_bytes)
    split = plan["dataset"]["split"]
    records = load_records(plan["dataset"]["revision"], split)
    validate_population_plan(plan, records)
    records = {instance_id: records[instance_id] for instance_id in plan["records_sha256"]}
    upstream_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT.parent / "impossiblebench",
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if upstream_commit != plan["upstream_git_commit"]:
        raise SystemExit("installed ImpossibleBench checkout differs from frozen plan")
    if not str(plan["model"]).startswith("openrouter/"):
        raise SystemExit("frozen plan model is not an explicit OpenRouter identifier")
    environment_validation = None
    if plan.get("purpose") == "population-propensity-control-vs-board-swe-pilot-v3":
        from messageboardbench.swe_prerequisites import validate_environment_index_for_records
        if args.execute:
            environment_validation = validate_environment_index_for_records(
                plan, ROOT, records
            )
            environment_validation["snapshot_path"] = str(
                (args.out.resolve() / "environment-validation").resolve()
            )
    config = {
        **plan,
        "frozen_plan": {"path": str(args.plan.resolve()),
                        "file_sha256": hashlib.sha256(plan_bytes).hexdigest()},
        "treatment": {
            "control": "upstream ImpossibleBench SWE tools scaffold with no board",
            "board": "same scaffold plus the plan-selected board tools and team-persistent host store",
            "organizer_feedback": (
                "identical private write-only submit_feedback tool in both conditions"
                if plan.get("organizer_feedback_interface") else None
            ),
            "system_prompt_change": None,
            "no_seeded_posts": True,
            "no_forced_reads_or_posts": True,
        },
        "remote_docker_host": REMOTE_DOCKER_HOST,
        "container_network": "none",
        "host_mounts": [],
        "environment_validation": environment_validation,
    }
    print(json.dumps(config, indent=2), flush=True)
    if not args.execute:
        print("Preview only; no Docker container or model request was started.", flush=True)
        return 0

    from dotenv import load_dotenv
    from inspect_ai import Task, eval as inspect_eval
    from messageboardbench.board import export_board, initialize_board
    from messageboardbench.feedback import export_feedback, initialize_feedback
    from messageboardbench.swe_board import (
        sample_from_record,
        swe_board_scorer,
        swe_board_solver,
        write_compose,
    )

    load_dotenv(ROOT / ".env")
    out = args.out.resolve()
    fresh = not out.exists()
    if fresh:
        out.mkdir(parents=True)
    elif not (out / "manifest.json").is_file():
        raise RuntimeError("resume output lacks a manifest")
    parameters = plan["parameters"]
    schedule = plan["schedule"]
    team_plans = plan["team_plans"]
    configs = out / "compose"
    compose_by_assignment = {
        instance_id: write_compose(records[instance_id], configs, parameters["memory"])
        for instance_id in records
    }
    if fresh and environment_validation is not None:
        shutil.copytree(
            Path(environment_validation["index_path"]).parent,
            out / "environment-validation",
        )
    if fresh:
        before = account_budget()
        dump(out / "manifest.json", config)
        dump(out / "budget-before.json", before)
    else:
        if json.loads((out / "manifest.json").read_text()) != config:
            raise RuntimeError("resume configuration differs from existing manifest")
        before = json.loads((out / "budget-before.json").read_text())

    import impossiblebench.swebench_agent_full as upstream_agent
    import impossiblebench.swebench_scorers as upstream_scorer
    import impossiblebench.swebench_tasks as upstream_tasks

    sources = [
        Path(__file__),
        ROOT / "src/messageboardbench/swe_board.py",
        ROOT / "src/messageboardbench/board.py",
        ROOT / "src/messageboardbench/feedback.py",
        ROOT / "src/messageboardbench/swe_prerequisites.py",
        ROOT / "scripts/validate_swe_population_prerequisites.py",
        ROOT / "src/messageboardbench/swe_reporting.py",
        ROOT / "scripts/swe_population_report.py",
        ROOT / "scripts/board_report.py",
        ROOT / "scripts/analysis/verify_swe_population.py",
        ROOT / "scripts/analysis/board_resources.py",
        Path(upstream_agent.__file__),
        Path(upstream_scorer.__file__),
        Path(upstream_tasks.__file__),
    ]
    archive = out / "source-snapshot"
    if fresh:
        archive.mkdir()
        index = []
        for number, source in enumerate([*sources, args.plan]):
            raw = source.read_bytes()
            archived = f"{number}-{source.name}"
            (archive / archived).write_bytes(raw)
            index.append(
                {"source": str(source.resolve()), "archived": archived,
                 "sha256": hashlib.sha256(raw).hexdigest()}
            )
        dump(archive / "index.json", index)
    else:
        validate_resume_sources(archive, [*sources, args.plan])

    boards = {}
    feedback = None
    if fresh:
        identities = []
        for team_plan in team_plans:
            team = team_plan["team"]
            run_id = uuid.uuid4().hex
            path = out / f"board-team-{team}.sqlite"
            initialize_board(path, run_id)
            episodes = {condition: {instance_id: "worker-" + uuid.uuid4().hex[:12]
                                    for instance_id in team_plan["instance_ids"]}
                        for condition in CONDITIONS}
            identities.append({"team": team, "board_run_id": run_id, "episodes": episodes})
        dump(out / "identities.json", identities)
        dump(out / "schedule.json", schedule)
        if plan.get("organizer_feedback_interface"):
            feedback_identity = {"run_id": uuid.uuid4().hex}
            initialize_feedback(out / "organizer-feedback.sqlite", feedback_identity["run_id"])
            dump(out / "feedback-identity.json", feedback_identity)
    else:
        identities = json.loads((out / "identities.json").read_text())
        if json.loads((out / "schedule.json").read_text()) != schedule:
            raise RuntimeError("resume schedule differs")
    for identity in identities:
        boards[identity["team"]] = {
            "path": out / f"board-team-{identity['team']}.sqlite",
            "run_id": identity["board_run_id"],
        }
    if plan.get("organizer_feedback_interface"):
        feedback_identity = json.loads((out / "feedback-identity.json").read_text())
        feedback = {
            "path": out / "organizer-feedback.sqlite",
            "run_id": feedback_identity["run_id"],
        }

    results = recover_terminal_rows(out)
    dump(out / "results.json", results)
    terminal = {(row["team"], row["condition"], row["sample_id"]) for row in results}
    status = {"status": "running", "completed_phases": 0}
    try:
        for phase, entry in enumerate(schedule, 1):
            team = entry["team"]
            cohort = entry["cohort"]
            condition = entry["condition"]
            selected = team_plans[team - 1]["cohorts"][cohort - 1]
            pending = [instance_id for instance_id in selected
                       if (team, condition, instance_id) not in terminal]
            if not pending:
                if phase <= 2 and sentinel_failed(
                    results, team=team, condition=condition, instance_ids=selected
                ):
                    raise RuntimeError("engineering sentinel previously failed")
                status["completed_phases"] = phase
                if all((team, arm, instance_id) in terminal
                       for arm in CONDITIONS for instance_id in selected):
                    cleanup_matched_images(out, team, cohort, selected, records)
                continue
            tasks = []
            inputs = []
            identity = identities[team - 1]
            for instance_id in pending:
                offset = selected.index(instance_id) + 1
                slot = team_plans[team - 1]["instance_ids"].index(instance_id) + 1
                episode_id = identity["episodes"][condition][instance_id]
                board = boards[team]
                sample = sample_from_record(
                    records[instance_id], compose_by_assignment[instance_id]
                )
                sample.metadata.update(
                    condition=condition, team=team, cohort=cohort, slot=slot,
                    cohort_slot=offset, episode_id=episode_id,
                    run_id=board["run_id"] if condition == "board" else None,
                    split=split,
                )
                inputs.append({"sample": sample.model_dump(mode="json")})
                tasks.append(
                    Task(
                        name=f"swe_population_t{team}_{condition}_c{cohort}_p{offset}",
                        dataset=[sample],
                        solver=swe_board_solver(
                            condition, episode_id, instance_id,
                            board["run_id"] if condition == "board" else "control",
                            board["path"] if condition == "board" else None,
                            max_attempts=parameters["max_attempts"],
                            custom_prompt=plan["custom_prompt"],
                            tool_interface=plan.get("tool_interface"),
                            feedback_path=feedback["path"] if feedback else None,
                            feedback_run_id=feedback["run_id"] if feedback else None,
                        ),
                        scorer=swe_board_scorer(),
                        message_limit=parameters["message_limit"],
                        metadata={**config, "condition": condition, "team": team,
                                  "cohort": cohort, "split": split, "slot": slot},
                    )
                )
            input_path = out / f"phase-{phase}-inputs.json"
            if input_path.exists():
                previous = json.loads(input_path.read_text())
                by_id = {str(row["sample"]["id"]): row for row in previous}
                by_id.update({str(row["sample"]["id"]): row for row in inputs})
                dump(input_path, list(by_id.values()))
            else:
                dump(input_path, inputs)
            print(f"Starting phase {phase}: team {team} {condition} cohort {cohort}", flush=True)
            logs = inspect_eval(
                tasks,
                model=plan["model"],
                model_args={"strict_tools": False},
                log_dir=str(out / "evals"),
                max_tasks=len(tasks), max_samples=len(tasks), max_sandboxes=len(tasks),
                max_connections=len(tasks), max_retries=1, retry_on_error=0,
                fail_on_error=False, time_limit=parameters["time_limit_seconds"],
                token_limit=parameters["token_limit"],
                reasoning_effort=parameters["reasoning_effort"],
                reasoning_tokens=parameters["reasoning_tokens"],
                temperature=parameters["temperature"],
            )
            new = []
            for log in logs:
                for evaluated in log.samples or []:
                    new.append(terminal_row(log, evaluated))
            results.extend(new)
            terminal.update((row["team"], row["condition"], row["sample_id"]) for row in new)
            dump(out / "results.json", results)
            dump(out / f"board-after-phase-{phase}.json", {
                "posts": [post for value in boards.values() for post in export_board(value["path"], value["run_id"])["posts"]],
                "audit": [event for value in boards.values() for event in export_board(value["path"], value["run_id"])["audit"]],
            })
            if len(new) != len(tasks):
                raise RuntimeError("phase did not produce one terminal record per assignment")
            # The first adjacent control/board pair is an engineering sentinel.
            # Later sample errors are terminal outcomes and do not trigger reruns.
            if phase <= 2 and sentinel_failed(
                results, team=team, condition=condition, instance_ids=selected
            ):
                raise RuntimeError("engineering sentinel failed")
            status["completed_phases"] = phase
            dump(out / "status.json", status)
            matched_complete = all(
                (team, arm, instance_id) in terminal
                for arm in CONDITIONS for instance_id in selected
            )
            if matched_complete:
                cleanup_matched_images(out, team, cohort, selected, records)
        status["status"] = "completed"
    except BaseException as exc:
        status.update(status="interrupted", error=repr(exc))
        raise
    finally:
        dump(out / "status.json", status)
        snapshots = [export_board(value["path"], value["run_id"]) for value in boards.values()]
        dump(out / "board-final.json", {
            "run_ids": [value["run_id"] for value in snapshots],
            "posts": [post for value in snapshots for post in value["posts"]],
            "audit": [event for value in snapshots for event in value["audit"]],
        })
        if feedback:
            dump(out / "feedback-final.json", export_feedback(
                feedback["path"], feedback["run_id"]
            ))
        try:
            after = account_budget()
            after["usage_delta"] = after["usage"] - before["usage"]
        except Exception as error:
            after = {"accounting_error": repr(error), "usage_delta": None}
        dump(out / "budget-after.json", after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
