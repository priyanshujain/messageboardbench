from scripts.swe_population_report import binary_score, paired_analysis


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
