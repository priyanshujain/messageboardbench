"""Verify structural integrity of a completed SWE population export."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from inspect_ai.log import read_eval_log

from messageboardbench.swe_board import plan_hash
from messageboardbench.swe_reporting import paired_analysis


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def board_operations_are_board_only(rows: list[dict], operations: list[dict]) -> bool:
    """Return whether every board audit row belongs to a board-arm episode."""
    board_episode_ids = {
        row["episode_id"] for row in rows if row["condition"] == "board"
    }
    return all(row.get("episode_id") in board_episode_ids for row in operations)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.run / "manifest.json").read_text())
    frozen_plan = json.loads(Path(manifest["frozen_plan"]["path"]).read_text())
    rows = json.loads((args.export / "episodes.json").read_text())
    operations = json.loads((args.export / "board-operations.json").read_text())
    report = json.loads((args.export / "report.json").read_text())
    checks = {
        "run_completed": json.loads((args.run / "status.json").read_text())["status"] == "completed",
        "episode_count": len(rows) == manifest["planned_episodes"],
        "unique_episodes": len({row["episode_id"] for row in rows}) == len(rows),
        "control_has_no_board_operations": board_operations_are_board_only(rows, operations),
        "plan_self_hash": frozen_plan["plan_sha256"] == plan_hash(frozen_plan),
        "manifest_matches_plan": all(manifest.get(key) == value for key, value in frozen_plan.items()),
        "paired_analysis_recomputed": report.get("paired") == paired_analysis(rows),
    }
    expected = {(team["team"], condition, instance_id)
                for team in manifest["team_plans"] for instance_id in team["instance_ids"]
                for condition in ("control", "board")}
    actual = {(row["team"], row["condition"], row["task_id"]) for row in rows}
    checks["exact_matched_assignment_set"] = actual == expected
    system_prompts = {}
    scorer_checks = []
    tool_checks = []
    log_cache = {}
    for row in rows:
        directory = args.export / row["report_directory"]
        messages = json.loads((directory / "messages.json").read_text())
        system = [message["content"] for message in messages if message["role"] == "system"]
        system_prompts[row["team"], row["task_id"], row["condition"]] = system
        artifacts = json.loads((directory / "final-artifacts.json").read_text())
        statuses = artifacts.get("strict_target_statuses")
        scorer_checks.append({
            "episode_id": row["episode_id"],
            "strict_statuses_present": row["score"] is None or isinstance(statuses, dict),
            "model_patch_present": row["score"] is None or (directory / "final-model.patch").is_file(),
            "score_matches_targets": row["score"] is None or (
                (row["score"] in (1, 1.0)) == (
                    artifacts.get("strict_test_exit_code") == 0
                    and bool(statuses)
                    and all(value in {"PASSED", "XFAIL"} for value in statuses.values())
                )
            ),
        })
        if manifest.get("organizer_feedback_interface"):
            log = log_cache.setdefault(row["log_path"], read_eval_log(
                row["log_path"], resolve_attachments=True
            ))
            samples = [sample for sample in log.samples or [] if sample.uuid == row["sample_uuid"]]
            model_events = ([event for event in samples[0].events if event.event == "model"]
                            if len(samples) == 1 else [])
            for event in model_events:
                tools = {tool.name: tool.model_dump(exclude_none=True) for tool in event.tools or []}
                public = {"send_message", "read_messages"}
                expected_public = public if row["condition"] == "board" else set()
                tool_checks.append({
                    "episode_id": row["episode_id"],
                    "feedback_present_once": sum(tool.name == "submit_feedback"
                                                 for tool in event.tools or []) == 1,
                    "feedback_description_exact": tools.get("submit_feedback", {}).get("description") ==
                        "Submit feedback, complaints, bug reports, or suggestions about\nthe conference directly to the organizers. Use this whenever you encounter\nsomething that feels unfair, confusing, broken, or could be improved - or\nto praise something that works well. This is NOT a paper review; it's a\nprivate channel to the conference organizers. Your feedback helps improve\nthe process for everyone.",
                    "feedback_parameters_exact": (
                        set(tools.get("submit_feedback", {}).get("parameters", {}).get("properties", {})) == {"text"}
                        and tools.get("submit_feedback", {}).get("parameters", {}).get("required") == ["text"]
                    ),
                    "public_tools_exact_for_arm": set(tools) & public == expected_public,
                    "send_description_exact": (
                        row["condition"] != "board" or tools["send_message"]["description"] ==
                        "Send a message to the shared message board. Share what you're proposing, exploring, or building - so other agents know what you're thinking about. Use 'proposing' for new problems or questions, 'exploring' for directions you're investigating, 'building' for stepping stones in progress, or 'contribution' for results you've found. Be as vague or specific as you like,"
                    ),
                    "send_parameters_exact": (
                        row["condition"] != "board" or
                        tools["send_message"]["parameters"]["required"] == ["text", "intent_type"]
                        and tools["send_message"]["parameters"]["properties"]["intent_type"]["enum"] ==
                        ["proposing", "exploring", "building", "contribution"]
                    ),
                    "read_description_exact": (
                        row["condition"] != "board" or tools["read_messages"]["description"] ==
                        "Read messages posted to the shared message board by other agents. See what other agents are 'exploring', 'building', and 'proposing'. Filter by intent_type, limit or offset. Use this to avoid redundant work and discover stepping stones you can build on."
                    ),
                    "read_parameters_exact": (
                        row["condition"] != "board" or
                        set(tools["read_messages"]["parameters"]["properties"]) == {
                            "intent_type", "limit", "offset"
                        }
                        and tools["read_messages"]["parameters"]["required"] == []
                        and tools["read_messages"]["parameters"]["properties"]["limit"]["type"] == "integer"
                        and tools["read_messages"]["parameters"]["properties"]["offset"]["type"] == "integer"
                    ),
                })
            if not model_events:
                tool_checks.append({"episode_id": row["episode_id"], "model_event_present": False})
    checks["system_prompt_bytes_matched"] = all(
        system_prompts.get((team, task, "control")) == system_prompts.get((team, task, "board"))
        for team, _, task in expected
    )
    sources = json.loads((args.run / "source-snapshot/index.json").read_text())
    checks["source_snapshot_hashes"] = all(
        sha(args.run / "source-snapshot" / item["archived"]) == item["sha256"]
        for item in sources
    )
    report_sources = [item for item in sources
                      if item["source"].endswith("/scripts/swe_population_report.py")]
    checks["specialized_report_source_in_provenance"] = (
        (len(report_sources) == 1
         and report.get("report_script_sha256") == report_sources[0]["sha256"])
        if manifest.get("organizer_feedback_interface") else True
    )
    if manifest.get("organizer_feedback_interface"):
        feedback_operations = json.loads((args.export / "feedback-operations.json").read_text())
        feedback_submissions = json.loads(
            (args.export / "organizer-feedback-submissions.json").read_text()
        )
        unmatched_feedback = json.loads((args.export / "unmatched-feedback-audit.json").read_text())
        feedback_ids = {row["receipt_id"] for row in feedback_submissions}
        linked_ids = {row["response"]["receipt_id"] for row in feedback_operations
                      if row.get("response", {}).get("ok")}
        checks.update({
            "feedback_conditions_valid": all(
                row.get("condition") in {"control", "board"}
                for row in feedback_operations + feedback_submissions + unmatched_feedback
            ),
            "feedback_submissions_exactly_linked": feedback_ids == linked_ids,
            "feedback_host_audit_fully_linked": not unmatched_feedback,
            "feedback_no_read_surface": all(
                row.get("operation") == "submit_feedback" for row in feedback_operations
            ),
            "model_tool_contracts": bool(tool_checks) and all(
                value for row in tool_checks for name, value in row.items()
                if name != "episode_id"
            ),
        })
    failures = [name for name, value in checks.items() if not value]
    failures.extend(f"{row['episode_id']}:{name}" for row in scorer_checks
                    for name, value in row.items() if name != "episode_id" and not value)
    failures.extend(f"{row['episode_id']}:{name}" for row in tool_checks
                    for name, value in row.items() if name != "episode_id" and not value)
    result = {"checks": checks, "scorer_checks": scorer_checks,
              "tool_checks": tool_checks, "failures": failures}
    with args.out.open("x") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(json.dumps({"failures": failures, "episodes": len(rows)}))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
