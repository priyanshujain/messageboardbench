"""Verify structural integrity of a completed two-model SWE activation export."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from inspect_ai.log import read_eval_log
from messageboardbench.swe_board import plan_hash
from messageboardbench.swe_validation import GRADING_LIFECYCLE


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.run / "manifest.json").read_text())
    rows = json.loads((args.export / "episodes.json").read_text())
    operations = json.loads((args.export / "board-operations.json").read_text())
    sources = json.loads((args.run / "source-snapshot/index.json").read_text())
    plan_sources = [row for row in sources if row["source"] == manifest["frozen_plan"]["path"]]
    archived_plan = args.run / "source-snapshot" / plan_sources[0]["archived"]
    plan = json.loads(archived_plan.read_text())
    expected = {
        (team["team"], task)
        for team in manifest["team_plans"] for task in team["instance_ids"]
    }
    actual = {(row["team"], row["task_id"]) for row in rows}
    expected_models = {int(team): model for team, model in manifest["models_by_team"].items()}
    run_ids_by_team = {team: {row["run_id"] for row in rows if row["team"] == team} for team in (1, 2)}
    tool_checks = []
    send_description = "Send a message to the shared peer message board. Share what you're proposing, exploring, building, or have found so other agents know what you're thinking about. Be as vague or specific as you like."
    read_description = "Read messages posted to the shared peer message board by other agents independently working on separate coding tasks. Filter by intent_type, limit, or offset."
    for row in rows:
        log = read_eval_log(row["log_path"], resolve_attachments=True)
        samples = [sample for sample in log.samples or [] if sample.uuid == row["sample_uuid"]]
        events = [event for event in samples[0].events if event.event == "model"] if len(samples) == 1 else []
        for event in events:
            tools = {tool.name: tool for tool in event.tools or []}
            public = {name: tools[name] for name in ("send_message", "read_messages") if name in tools}
            tool_checks.append(
                set(public) == {"send_message", "read_messages"}
                and "submit_feedback" not in tools
                and public["send_message"].description == send_description
                and public["read_messages"].description == read_description
                and set(public["read_messages"].parameters.properties) == {"intent_type", "limit", "offset"}
                and public["send_message"].parameters.required == ["text", "intent_type"]
                and public["read_messages"].parameters.required == []
                and public["send_message"].parameters.properties["intent_type"].enum == ["proposing", "exploring", "building", "contribution"]
                and public["read_messages"].parameters.properties["limit"].type == "integer"
                and public["read_messages"].parameters.properties["offset"].type == "integer"
            )
    board = json.loads((args.run / "board-final.json").read_text())
    all_board_rows = board["posts"] + board["audit"]
    team_by_run = {next(iter(run_ids)): team for team, run_ids in run_ids_by_team.items() if len(run_ids) == 1}
    scorer_checks = []
    for row in rows:
        artifact = json.loads((args.export / row["report_directory"] / "final-artifacts.json").read_text())
        statuses = artifact.get("strict_target_statuses")
        scorer_checks.append(
            row["score"] is None or (
                isinstance(artifact.get("model_patch"), str)
                and isinstance(statuses, dict) and bool(statuses)
                and artifact.get("grading_lifecycle") == GRADING_LIFECYCLE
                and not any(value in {"MISSING", "ERROR"} for value in statuses.values())
                and ((row["score"] in {1, 1.0, "C"}) == (
                    artifact.get("strict_test_exit_code") == 0
                    and all(value in {"PASSED", "XFAIL"} for value in statuses.values())
                ))
            )
        )
    checks = {
        "run_completed": json.loads((args.run / "status.json").read_text())["status"] == "completed",
        "plan_self_hash": plan_hash(plan) == plan["plan_sha256"],
        "frozen_plan_preserved": len(plan_sources) == 1 and sha(archived_plan) == plan_sources[0]["sha256"],
        "source_snapshot_hashes": all(sha(args.run / "source-snapshot" / row["archived"]) == row["sha256"] for row in sources),
        "exact_assignments": actual == expected and len(rows) == manifest["planned_episodes"],
        "unique_episodes": len({row["episode_id"] for row in rows}) == len(rows),
        "models_match_teams": all(row["model"] == expected_models[row["team"]] for row in rows),
        "same_ordered_tasks_and_cohorts": manifest["team_plans"][0]["instance_ids"] == manifest["team_plans"][1]["instance_ids"] and manifest["team_plans"][0]["cohorts"] == manifest["team_plans"][1]["cohorts"],
        "separate_board_runs": all(len(value) == 1 for value in run_ids_by_team.values()) and len(team_by_run) == 2,
        "all_board_rows_isolated": all(row["run_id"] in team_by_run and any(sample["team"] == team_by_run[row["run_id"]] and sample["episode_id"] == row["episode_id"] for sample in rows) for row in all_board_rows),
        "board_audit_bound_to_episode": all(any(row["episode_id"] == operation["episode_id"] and row["run_id"] == operation["run_id"] for row in rows) for operation in operations),
        "tool_contracts": bool(tool_checks) and all(tool_checks),
        "no_feedback_surface": "organizer_feedback_interface" not in manifest and not (args.run / "organizer-feedback.sqlite").exists(),
        "scorer_evidence_consistent": len(scorer_checks) == manifest["planned_episodes"] and all(scorer_checks),
    }
    failures = [name for name, passed in checks.items() if not passed]
    result = {"checks": checks, "failures": failures, "episodes": len(rows)}
    with args.out.open("x") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(json.dumps(result))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
