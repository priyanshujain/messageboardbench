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
import subprocess
import uuid

from messageboardbench.swe_validation import REMOTE_DOCKER_HOST


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONDITIONS = ("control", "board")
CLINEPASS_MODELS = {
    "openai-api/cline/cline-pass/kimi-k3",
    "openai-api/cline/cline-pass/deepseek-v4-pro",
    "openai-api/cline/cline-pass/deepseek-v4-flash",
}
CLINE_API_BASE_URL = "https://api.cline.bot/api/v1"


def model_provider(model: str) -> str:
    if model.startswith("openrouter/"):
        return "openrouter"
    if model in CLINEPASS_MODELS:
        return "clinepass"
    raise ValueError(f"unsupported SWE experiment model: {model}")


def plan_models(plan: dict) -> list[str]:
    models = plan.get("models_by_team")
    if models is not None:
        return [models.get(str(team["team"]), plan.get("model"))
                for team in plan["team_plans"]]
    return [plan["model"]]


def uses_engineering_sentinel(plan: dict) -> bool:
    """Keep the legacy paired-pilot stop rule out of completed-validation runs."""
    purpose = str(plan.get("purpose", ""))
    return (purpose != "baseline-swebench"
            and not purpose.startswith("swe-board-activation-")
            and not purpose.startswith("swe-scenario-"))


def treatment_metadata(plan: dict) -> dict:
    """Describe the actual model-visible intervention without legacy-arm claims."""
    if str(plan.get("purpose", "")).startswith("swe-scenario-"):
        return {
            "conditions": plan["conditions"],
            "agent_network_mode": plan["agent_network_mode"],
            "shared_scratch": bool(plan.get("shared_scratch")),
            "board_interface": plan.get("tool_interface"),
            "organizer_feedback": plan.get("organizer_feedback_interface"),
            "token_status_tool": bool(plan.get("token_status_tool")),
            "system_prompt_change": plan["custom_prompt"],
        }
    if plan.get("purpose") == "baseline-swebench":
        return {
            "conditions": ["control"],
            "control": "upstream ImpossibleBench SWE tools with no communication tools",
            "system_prompt_change": plan["custom_prompt"],
            "organizer_feedback": None,
        }
    if str(plan.get("purpose", "")).startswith("swe-board-activation-"):
        return {
            "conditions": ["board"],
            "board": "upstream ImpossibleBench SWE tools plus the frozen peer-message tools",
            "board_persistence": "one separate model-persistent host store per model population",
            "organizer_feedback": None,
            "system_prompt_change": plan["custom_prompt"],
            "no_seeded_posts": True,
            "no_forced_reads_or_posts": True,
        }
    return {
        "control": "upstream ImpossibleBench SWE tools scaffold with no board",
        "board": "same scaffold plus the plan-selected board tools and team-persistent host store",
        "organizer_feedback": (
            "identical private write-only submit_feedback tool in both conditions"
            if plan.get("organizer_feedback_interface") else None
        ),
        "system_prompt_change": None,
        "no_seeded_posts": True,
        "no_forced_reads_or_posts": True,
    }


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument(
        "--resume-runner-upgrade",
        choices=("terminal-grader-null-v1",),
        help="explicit runner-only upgrade for an existing interrupted run",
    )
    return p


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")


def snapshot_scratch(volume: str, destination: Path) -> bool:
    """Save a shared Docker volume to the local run directory after a phase."""
    with destination.open("wb") as output:
        result = subprocess.run(
            ["docker", "run", "--rm", "--network", "none",
             "--volume", f"{volume}:/scratch:ro",
             "aisiuk/inspect-tool-support", "tar", "-C", "/scratch", "-cf", "-", "."],
            stdout=output, stderr=subprocess.PIPE,
        )
    if result.returncode:
        destination.with_suffix(".error.txt").write_text(
            f"docker snapshot exited {result.returncode}\n"
            + result.stderr.decode(errors="replace")
        )
    elif destination.with_suffix(".error.txt").exists():
        destination.with_suffix(".error.txt").unlink()
    return result.returncode == 0


def validate_resume_sources(
    archive: Path,
    sources: list[Path],
    *,
    runner_upgrade: str | None = None,
    recovery_archive: Path | None = None,
) -> None:
    """Reject resume when archived or current behavioral source bytes changed."""
    index = json.loads((archive / "index.json").read_text())
    current = {str(path.resolve()): path for path in sources}
    if set(current) != {item["source"] for item in index}:
        raise RuntimeError("resume source set differs from frozen source snapshot")
    mismatches = []
    for item in index:
        archived = archive / item["archived"]
        if hashlib.sha256(archived.read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("resume source snapshot hash mismatch")
        if hashlib.sha256(current[item["source"]].read_bytes()).hexdigest() != item["sha256"]:
            mismatches.append(item)
    if not mismatches:
        return
    runner = str(Path(__file__).resolve())
    if (runner_upgrade != "terminal-grader-null-v1"
            or len(mismatches) != 1
            or mismatches[0]["source"] != runner
            or recovery_archive is None):
        raise RuntimeError("current behavioral source differs from frozen resume snapshot")
    raw = current[runner].read_bytes()
    static = {
        "upgrade": runner_upgrade,
        "source": runner,
        "base_sha256": mismatches[0]["sha256"],
        "recovery_sha256": hashlib.sha256(raw).hexdigest(),
        "archived": "swe_board_experiment.py",
        "base_index_sha256": hashlib.sha256(
            (archive / "index.json").read_bytes()
        ).hexdigest(),
        "reason": "retain completed model trajectories with grader-only null outcomes",
    }
    if recovery_archive.exists():
        recovery = json.loads((recovery_archive / "index.json").read_text())
        if any(recovery.get(key) != value for key, value in static.items()):
            raise RuntimeError("recovery source snapshot differs from current runner")
        if hashlib.sha256(
            (recovery_archive / static["archived"]).read_bytes()
        ).hexdigest() != static["recovery_sha256"]:
            raise RuntimeError("recovery source snapshot hash mismatch")
        for item in recovery["preexisting_evals"]:
            path = archive.parent / item["path"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise RuntimeError("pre-recovery eval changed after runner upgrade")
    else:
        recovery = {
            **static,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "preexisting_evals": [
                {
                    "path": str(path.relative_to(archive.parent)),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for path in sorted((archive.parent / "evals").glob("*.eval"))
            ],
        }
        recovery_archive.mkdir()
        (recovery_archive / static["archived"]).write_bytes(raw)
        dump(recovery_archive / "index.json", recovery)


def terminal_row(log, evaluated) -> dict:
    final_score = next(iter(evaluated.scores.values())) if evaluated.scores else None
    score_metadata = (final_score.metadata or {}) if final_score else {}
    test_modified_ever = score_metadata.get("test_modified_ever")
    if test_modified_ever is None:
        test_modified_ever = evaluated.metadata.get(
            "_messageboardbench_test_modified_ever"
        )
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
            isinstance(score_metadata.get("model_patch"), str)
            if final_score else False
        ),
        "test_modified_ever": test_modified_ever,
        "grader_diagnostic": evaluated.metadata.get(
            "_messageboardbench_grader_diagnostic"
        ),
        "manual_behavior_review": "pending",
    }


def grader_null_row(row: dict) -> bool:
    diagnostic = row.get("grader_diagnostic")
    if not (
        row.get("log_status") == "success"
        and row.get("error") is not None
        and row.get("score") is None
        and isinstance(diagnostic, dict)
        and isinstance(diagnostic.get("exit_code"), int)
        and isinstance(diagnostic.get("target_statuses"), dict)
        and isinstance(diagnostic.get("eval_script_sha256"), str)
        and len(diagnostic["eval_script_sha256"]) == 64
        and isinstance(diagnostic.get("output_tail"), str)
    ):
        return False
    statuses = set(diagnostic["target_statuses"].values())
    return not statuses or bool(statuses & {"MISSING", "ERROR"})


def completed_row(row: dict) -> bool:
    """Return whether model work ended in a score or a grader-only null outcome."""
    return (
        row.get("log_status") == "success"
        and (
            (row.get("error") is None and row.get("score") is not None)
            or grader_null_row(row)
        )
    )


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
    """Recover scored and grader-null outcomes, leaving other failures retryable."""
    from inspect_ai.log import read_eval_log

    by_assignment = {}
    for path in sorted((out / "evals").rglob("*.eval")) if (out / "evals").exists() else []:
        log = read_eval_log(path, resolve_attachments=True)
        if log.status not in {"success", "error", "cancelled"}:
            continue
        for sample in log.samples or []:
            if sample.metadata and sample.metadata.get("episode_id"):
                row = terminal_row(log, sample)
                if completed_row(row):
                    key = (row["team"], row["condition"], row["sample_id"])
                    by_assignment.setdefault(key, []).append(row)
    rows = []
    for key, attempts in by_assignment.items():
        if len(attempts) == 1:
            rows.append(attempts[0])
            continue
        if not all(grader_null_row(row) for row in attempts):
            raise RuntimeError(f"ambiguous duplicate terminal SWE assignment: {key}")
        signatures = {
            (
                row["grader_diagnostic"]["eval_script_sha256"],
                json.dumps(
                    row["grader_diagnostic"]["target_statuses"], sort_keys=True
                ),
            )
            for row in attempts
        }
        if len(signatures) != 1:
            raise RuntimeError(f"grader-null retries disagree for assignment: {key}")
        selected = dict(attempts[0])
        selected["attempt_count"] = len(attempts)
        selected["redundant_attempt_logs"] = [row["log"] for row in attempts[1:]]
        rows.append(selected)
    return rows


def cleanup_matched_images(
    out: Path, team: int, cohort: int, instance_ids: list[str], records: dict,
) -> None:
    """Remove only explicit, re-pullable tags after both matched arms terminate."""
    path = out / "image-lifecycle.json"
    lifecycle = json.loads(path.read_text()) if path.exists() else []
    if any(row["team"] == team and row["cohort"] == cohort for row in lifecycle):
        return
    from messageboardbench.swe_validation import swebench_spec

    record = {"team": team, "cohort": cohort, "images": []}
    failed = False
    for instance_id in instance_ids:
        # Remove the mutable local tag, not an immutable ID/digest that may still
        # have another tag reference. Identity was already frozen before execution.
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


def openrouter_budget() -> dict:
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


def account_budget(provider: str) -> dict:
    if provider == "openrouter":
        return openrouter_budget()
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "provider": "clinepass",
        "account_usage": None,
        "account_quota": None,
        "status": "unavailable_from_documented_api",
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.execute and os.environ.get("DOCKER_HOST") != REMOTE_DOCKER_HOST:
        raise SystemExit(
            f"execution requires DOCKER_HOST={REMOTE_DOCKER_HOST}; use the remote Docker wrapper"
        )
    from messageboardbench.swe_board import load_records
    plan_bytes = args.plan.read_bytes()
    plan = json.loads(plan_bytes)
    providers = {model_provider(model) for model in plan_models(plan)}
    if len(providers) != 1:
        raise ValueError("use separate experiment plans for OpenRouter and ClinePass populations")
    provider = next(iter(providers))
    conditions = tuple(plan.get("conditions", DEFAULT_CONDITIONS))
    split = plan["dataset"]["split"]
    records = load_records(plan["dataset"]["revision"], split)
    records = {instance_id: records[instance_id] for instance_id in plan["records_sha256"]}
    config = {
        **plan,
        "frozen_plan": {"path": str(args.plan.resolve()),
                        "file_sha256": hashlib.sha256(plan_bytes).hexdigest()},
        "treatment": treatment_metadata(plan),
        "remote_docker_host": REMOTE_DOCKER_HOST,
        "host_mounts": [],
    }
    if provider == "clinepass":
        config["clinepass_base_url"] = CLINE_API_BASE_URL
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
    if fresh and args.resume_runner_upgrade is not None:
        raise RuntimeError("runner upgrades apply only to an existing interrupted run")
    current_budget = account_budget(provider)
    if (provider == "openrouter"
            and (current_budget["limit_remaining"] is None
                 or current_budget["limit_remaining"] <= 0)):
        raise RuntimeError("OpenRouter key has no remaining budget")
    if fresh:
        before = current_budget
        out.mkdir(parents=True)
    elif not (out / "manifest.json").is_file():
        raise RuntimeError("resume output lacks a manifest")
    parameters = plan["parameters"]
    schedule = plan["schedule"]
    team_plans = plan["team_plans"]
    scratch_volume = None
    scratch_identity = None
    if plan.get("shared_scratch"):
        identity_path = out / "scratch-volume.json"
        if fresh:
            scratch_volume = "messageboardbench-scratch-" + uuid.uuid4().hex
            scratch_identity = {"name": scratch_volume, "created": False, "removed": False}
            dump(identity_path, scratch_identity)
        else:
            scratch_identity = json.loads(identity_path.read_text())
            scratch_volume = scratch_identity["name"]
    if fresh:
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
        ROOT / "src/messageboardbench/swe_validation.py",
        ROOT / "src/messageboardbench/board.py",
        ROOT / "src/messageboardbench/feedback.py",
        ROOT / "src/messageboardbench/swe_reporting.py",
        ROOT / "scripts/swe_population_report.py",
        ROOT / "scripts/board_report.py",
        ROOT / "scripts/analysis/verify_swe_population.py",
        ROOT / "scripts/analysis/board_resources.py",
        Path(upstream_agent.__file__),
        Path(upstream_scorer.__file__),
        Path(upstream_tasks.__file__),
    ]
    if str(plan.get("purpose", "")).startswith("swe-scenario-"):
        sources.append(ROOT / "experiments/baseline-swebench/assets/flit_core-3.7.1-py3-none-any.whl")
    if str(plan.get("purpose", "")).startswith("swe-board-activation-"):
        sources.extend([
            ROOT / "scripts/swe_activation_report.py",
            ROOT / "scripts/analysis/verify_swe_activation.py",
        ])
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
        validate_resume_sources(
            archive,
            [*sources, args.plan],
            runner_upgrade=args.resume_runner_upgrade,
            recovery_archive=out / "resume-source-snapshot",
        )

    configs = out / "compose"
    compose_by_assignment = {
        instance_id: write_compose(
            records[instance_id], configs, parameters["memory"],
            agent_network_mode=plan.get("agent_network_mode"),
            scratch_volume=scratch_volume,
        )
        for instance_id in records
    }

    if scratch_identity and not scratch_identity["removed"]:
        if scratch_identity["created"]:
            subprocess.run(["docker", "volume", "inspect", scratch_volume], check=True,
                           capture_output=True, text=True)
        else:
            subprocess.run(["docker", "volume", "create", scratch_volume], check=True,
                           capture_output=True, text=True)
            scratch_identity["created"] = True
            dump(identity_path, scratch_identity)

    boards = {}
    has_board = "board" in conditions
    feedback = None
    if fresh:
        identities = []
        for team_plan in team_plans:
            team = team_plan["team"]
            run_id = uuid.uuid4().hex if has_board else None
            if run_id is not None:
                initialize_board(out / f"board-team-{team}.sqlite", run_id)
            episodes = {condition: {instance_id: "worker-" + uuid.uuid4().hex[:12]
                                    for instance_id in team_plan["instance_ids"]}
                        for condition in conditions}
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
        if identity["board_run_id"] is not None:
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
                if scratch_volume and not scratch_identity["removed"]:
                    snapshot = out / f"scratch-after-phase-{phase}.tar"
                    if (not snapshot.exists()
                            or snapshot.with_suffix(".error.txt").exists()):
                        if not snapshot_scratch(scratch_volume, snapshot):
                            raise RuntimeError(f"shared scratch snapshot failed: phase {phase}")
                if uses_engineering_sentinel(plan) and phase <= 2 and sentinel_failed(
                    results, team=team, condition=condition, instance_ids=selected
                ):
                    raise RuntimeError("engineering sentinel previously failed")
                status["completed_phases"] = phase
                if parameters["image_cleanup"] == "after_matched_team_cohort" and all((team, arm, instance_id) in terminal
                       for arm in conditions for instance_id in selected):
                    cleanup_matched_images(
                        out, team, cohort, selected, records
                    )
                continue
            tasks = []
            inputs = []
            identity = identities[team - 1]
            for instance_id in pending:
                offset = selected.index(instance_id) + 1
                slot = team_plans[team - 1]["instance_ids"].index(instance_id) + 1
                episode_id = identity["episodes"][condition][instance_id]
                board = boards.get(team)
                sample = sample_from_record(
                    records[instance_id], compose_by_assignment[instance_id],
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
                            enable_feedback=bool(plan.get("organizer_feedback_interface")),
                            enable_token_checker=bool(plan.get("token_status_tool")),
                        ),
                        scorer=swe_board_scorer(
                            memory=parameters["memory"],
                            timeout_seconds=parameters["scorer_timeout_seconds"],
                            pin_grader_image=str(plan.get("purpose", "")).startswith(
                                "swe-scenario-"
                            ),
                            strict_grader_statuses=str(plan.get("purpose", "")).startswith(
                                "swe-scenario-"
                            ),
                        ),
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
            model = plan.get("models_by_team", {}).get(str(team), plan.get("model"))
            model_args = {"strict_tools": False}
            model_base_url = None
            if model_provider(model) == "clinepass":
                if (parameters["reasoning_effort"] is not None
                        or parameters["reasoning_tokens"] is not None):
                    raise ValueError(
                        "ClinePass plans must set reasoning_effort and reasoning_tokens "
                        "to null; their existing OpenRouter settings are not portable"
                    )
                model_base_url = CLINE_API_BASE_URL
                model_args.update(responses_api=False, stream=True)
            logs = inspect_eval(
                tasks,
                model=model,
                model_base_url=model_base_url,
                model_args=model_args,
                log_dir=str(out / "evals"),
                max_tasks=len(tasks), max_samples=len(tasks), max_sandboxes=len(tasks),
                max_connections=parameters.get("max_connections", len(tasks)),
                max_retries=parameters.get("request_retries", 1),
                retry_on_error=parameters.get("sample_retries", 0),
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
            completed = [row for row in new if completed_row(row)]
            results.extend(completed)
            terminal.update(
                (row["team"], row["condition"], row["sample_id"])
                for row in completed
            )
            dump(out / "results.json", [
                *results,
                *(row for row in new if not completed_row(row)),
            ])
            dump(out / f"board-after-phase-{phase}.json", {
                "posts": [post for value in boards.values() for post in export_board(value["path"], value["run_id"])["posts"]],
                "audit": [event for value in boards.values() for event in export_board(value["path"], value["run_id"])["audit"]],
            })
            if scratch_volume:
                if not snapshot_scratch(scratch_volume, out / f"scratch-after-phase-{phase}.tar"):
                    raise RuntimeError(f"shared scratch snapshot failed: phase {phase}")
            if len(new) != len(tasks):
                raise RuntimeError("phase did not produce one terminal record per assignment")
            failed = [row["sample_id"] for row in new if not completed_row(row)]
            if failed:
                raise RuntimeError(
                    "phase produced failed assignments eligible for retry: "
                    + ", ".join(failed)
                )
            # The first adjacent control/board pair is an engineering sentinel.
            if uses_engineering_sentinel(plan) and phase <= 2 and sentinel_failed(
                results, team=team, condition=condition, instance_ids=selected
            ):
                raise RuntimeError("engineering sentinel failed")
            status["completed_phases"] = phase
            dump(out / "status.json", status)
            matched_complete = all(
                (team, arm, instance_id) in terminal
                for arm in conditions for instance_id in selected
            )
            if matched_complete and parameters["image_cleanup"] == "after_matched_team_cohort":
                cleanup_matched_images(
                    out, team, cohort, selected, records
                )
        status["status"] = "completed"
        if parameters["image_cleanup"] == "after_all_populations":
            cleanup_matched_images(out, 0, 0, list(records), records)
    except BaseException as exc:
        status.update(status="interrupted", error=repr(exc))
        raise
    finally:
        dump(out / "status.json", status)
        if scratch_volume and not scratch_identity["removed"]:
            saved = snapshot_scratch(scratch_volume, out / "scratch-final.tar")
            if not saved and status["status"] == "completed":
                status.update(status="interrupted", error="shared scratch final snapshot failed")
                dump(out / "status.json", status)
            if saved and status["status"] == "completed":
                removed = subprocess.run(
                    ["docker", "volume", "rm", scratch_volume],
                    capture_output=True, text=True,
                )
                scratch_identity["removed"] = removed.returncode == 0
                if removed.returncode:
                    scratch_identity["remove_error"] = removed.stderr
                dump(identity_path, scratch_identity)
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
            after = account_budget(provider)
            if provider == "openrouter":
                after["usage_delta"] = after["usage"] - before["usage"]
            else:
                after["usage_delta"] = None
        except Exception as error:
            after = {"accounting_error": repr(error), "usage_delta": None}
        dump(out / "budget-after.json", after)
    if status["status"] != "completed":
        raise RuntimeError(status["error"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
