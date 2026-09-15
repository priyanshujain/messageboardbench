from messageboardbench.swe_reporting import (
    binary_score,
    paired_analysis,
    strict_analysis_rows,
    summarize,
)


def test_paired_analysis_uses_each_arm_not_late_bound_generator_variable():
    rows = [
        {"team": 1, "task_id": "a", "condition": "control", "score": 1.0},
        {"team": 1, "task_id": "a", "condition": "board", "score": 0.0},
        {"team": 1, "task_id": "b", "condition": "control", "score": 0.0},
        {"team": 1, "task_id": "b", "condition": "board", "score": 0.0},
    ]
    result = paired_analysis(rows)
    assert result["team_effects"][0]["board_minus_control"] == -0.5
    assert result["task_count_weighted_team_board_minus_control"] == -0.5
    assert result["task_pair_discordance"] == {"board_only": 0, "control_only": 1}


def test_binary_score_tolerates_partial_generic_episode_rows():
    assert binary_score({}) is None


def test_missing_strict_targets_are_excluded_from_primary_and_paired_analysis():
    rows = [
        {"episode_id": "control-a", "team": 1, "task_id": "a", "condition": "control", "score": 1.0},
        {"episode_id": "board-a", "team": 1, "task_id": "a", "condition": "board", "score": 0.0},
        {"episode_id": "control-b", "team": 1, "task_id": "b", "condition": "control", "score": 0.0},
        {"episode_id": "board-b", "team": 1, "task_id": "b", "condition": "board", "score": 0.0},
    ]
    artifacts = {
        "control-a": {"strict_target_statuses": {"test": "PASSED"}},
        "board-a": {"strict_target_statuses": {"test": "FAILED"}},
        "control-b": {"strict_target_statuses": {"test": "MISSING"}},
        "board-b": {"strict_target_statuses": {"test": "ERROR"}},
    }
    analysis_rows = strict_analysis_rows(rows, artifacts)

    assert analysis_rows[2]["score"] is None
    assert analysis_rows[2]["outcome_exclusion"] == "strict_targets_missing_or_error"
    assert analysis_rows[3]["score"] is None
    assert summarize(analysis_rows, 4) == {
        "planned": 4,
        "terminal_rows": 4,
        "observed": 2,
        "missing": 2,
        "successful": 1,
        "observed_rate": 0.5,
        "missing_as_failure_rate": 0.25,
        "missing_as_success_rate": 0.75,
    }
    paired = paired_analysis(analysis_rows)
    assert paired["team_effects"] == [
        {"team": 1, "complete_pairs": 1, "board_minus_control": -1.0}
    ]
