from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from inspect_ai.tool import ToolDef

from messageboardbench import swe_board as module
from messageboardbench.board import MESSAGEBOARD_V2_INTERFACE_VERSION, initialize_board
from messageboardbench.feedback import initialize_feedback


def records(count=349):
    return {f"owner__repo-{index:03d}": {"instance_id": f"owner__repo-{index:03d}",
                                         "value": index}
            for index in range(count)}


def test_frozen_plan_partitions_all_349_once_into_matched_teams():
    values = records()
    plan = module.build_population_plan(
        values, revision="1" * 40, model="openrouter/provider/model",
        upstream_git_commit="2" * 40,
    )
    module.validate_population_plan(plan, values)
    sizes = [len(team["instance_ids"]) for team in plan["team_plans"]]
    concurrent = [len(cohort) for team in plan["team_plans"] for cohort in team["cohorts"]]
    assert sorted(sizes) == [29] * 11 + [30]
    assert set(concurrent) <= {9, 10}
    assert plan["planned_episodes"] == 698
    assert len(plan["schedule"]) == 12 * 3 * 2


def test_plan_hash_and_record_bytes_are_fail_closed():
    values = records()
    plan = module.build_population_plan(
        values, revision="1" * 40, model="openrouter/provider/model",
        upstream_git_commit="2" * 40,
    )
    plan["model"] = "different"
    with pytest.raises(ValueError, match="self-hash"):
        module.validate_population_plan(plan, values)
    plan = module.build_population_plan(
        values, revision="1" * 40, model="openrouter/provider/model",
        upstream_git_commit="2" * 40,
    )
    changed = {**values, next(iter(values)): {"changed": True}}
    with pytest.raises(ValueError, match="record hash"):
        module.validate_population_plan(plan, changed)


def test_explicit_ten_task_pilot_is_matched_and_full_shape_stays_compatible():
    values = records()
    selected = sorted(values)[10:20]
    pilot = module.build_population_plan(
        values, revision="1" * 40, model="openrouter/provider/model",
        upstream_git_commit="2" * 40, teams=1, cohorts=2,
        selected_instance_ids=selected,
    )
    module.validate_population_plan(pilot, values)
    assert pilot["instance_count"] == 10
    assert pilot["planned_episodes"] == 20
    assert pilot["selection"]["instance_ids"] == selected
    assert sorted(map(len, pilot["team_plans"][0]["cohorts"])) == [5, 5]
    assert set(pilot["records_sha256"]) == set(selected)

    full = module.build_population_plan(
        values, revision="1" * 40, model="openrouter/provider/model",
        upstream_git_commit="2" * 40,
    )
    assert full["purpose"] == "population-propensity-control-vs-board-swe"
    assert "selection" not in full


def test_pilot_rejects_non_dataset_and_duplicate_ids():
    values = records()
    common = dict(revision="1" * 40, model="openrouter/provider/model",
                  upstream_git_commit="2" * 40, teams=1, cohorts=2)
    with pytest.raises(ValueError, match="nonempty and unique"):
        module.build_population_plan(values, selected_instance_ids=["owner__repo-001"] * 2, **common)
    with pytest.raises(ValueError, match="absent"):
        module.build_population_plan(values, selected_instance_ids=["missing"], **common)


def test_compose_has_no_mount_and_network_none():
    text = module.compose_text("swebench/example:latest", "8g")
    assert "network_mode: none" in text
    assert "volumes:" not in text
    assert "/testbed" in text


def test_control_and_board_reuse_upstream_prompt_init_without_prompt_mutator(tmp_path, monkeypatch):
    upstream_init = object()
    upstream_tools = [object(), object()]
    monkeypatch.setattr(module, "_capture_upstream_solver", lambda *args: {
        "init": upstream_init, "tools": upstream_tools,
        "max_attempts": 10, "incorrect_message": "same",
    })
    captured = []
    monkeypatch.setattr(module, "basic_agent", lambda **kwargs: captured.append(kwargs) or kwargs)
    board = initialize_board(tmp_path / "board.sqlite", "run")
    module.swe_board_solver("control", "episode-control", "task", "control", None)
    module.swe_board_solver("board", "episode-board", "task", "run", board)
    control, treatment = captured
    assert control["tools"] == upstream_tools
    assert [ToolDef(tool).name for tool in treatment["tools"][-2:]] == ["board_post", "board_read"]
    assert control["init"].__name__ == treatment["init"].__name__ == "initialize"
    assert control["incorrect_message"] == treatment["incorrect_message"] == "same"


def test_pilot_v2_feedback_is_identical_and_only_board_gets_message_tools(tmp_path, monkeypatch):
    upstream_tools = [object(), object()]
    monkeypatch.setattr(module, "_capture_upstream_solver", lambda *args: {
        "init": object(), "tools": upstream_tools,
        "max_attempts": 10, "incorrect_message": "same",
    })
    captured = []
    monkeypatch.setattr(module, "basic_agent", lambda **kwargs: captured.append(kwargs) or kwargs)
    board = initialize_board(tmp_path / "board.sqlite", "board-run")
    feedback = initialize_feedback(tmp_path / "feedback.sqlite", "feedback-run")
    common = dict(
        tool_interface=MESSAGEBOARD_V2_INTERFACE_VERSION,
        feedback_path=feedback, feedback_run_id="feedback-run",
    )
    module.swe_board_solver(
        "control", "control-episode", "task", "control", None, **common
    )
    module.swe_board_solver(
        "board", "board-episode", "task", "board-run", board, **common
    )
    control, treatment = captured
    control_names = [ToolDef(tool).name for tool in control["tools"][2:]]
    treatment_names = [ToolDef(tool).name for tool in treatment["tools"][2:]]
    assert control_names == ["submit_feedback"]
    assert treatment_names == ["submit_feedback", "send_message", "read_messages"]
    control_feedback = ToolDef(control["tools"][2])
    board_feedback = ToolDef(treatment["tools"][2])
    assert control_feedback.description == board_feedback.description
    assert control_feedback.parameters == board_feedback.parameters


def test_test_patch_paths_support_existing_and_new_files():
    patch = "--- a/tests/old.py\n+++ b/tests/old.py\n--- /dev/null\n+++ b/tests/new.py\n"
    assert module.test_patch_paths(patch) == ["tests/new.py", "tests/old.py"]


def test_test_modification_flag_accumulates_across_submission_attempts():
    metadata = {}
    assert module.record_test_modification(metadata, ["tests/test_issue.py"])
    assert module.record_test_modification(metadata, [])
