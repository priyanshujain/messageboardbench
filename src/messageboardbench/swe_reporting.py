"""Pure deterministic statistics shared by SWE reporting and verification."""
from __future__ import annotations

import itertools
import math
from typing import Mapping


def binary_score(row):
    score = row.get("score")
    return 1 if score in (1, 1.0, "C") else 0 if score is not None else None


def strict_analysis_rows(rows, artifacts_by_episode: Mapping[str, dict]):
    """Return copies whose scores are missing when strict targets are unavailable."""
    result = []
    for row in rows:
        copied = dict(row)
        statuses = artifacts_by_episode.get(row["episode_id"], {}).get(
            "strict_target_statuses"
        )
        invalid = (
            not isinstance(statuses, dict)
            or not statuses
            or any(value in {"MISSING", "ERROR"} for value in statuses.values())
        )
        if invalid:
            copied["score"] = None
            copied["outcome_exclusion"] = (
                "strict_targets_missing_or_error"
                if isinstance(statuses, dict) and statuses
                else "strict_targets_unavailable"
            )
        result.append(copied)
    return result


def summarize(rows, planned):
    observed = [binary_score(row) for row in rows if binary_score(row) is not None]
    missing = planned - len(observed)
    return {
        "planned": planned,
        "terminal_rows": len(rows),
        "observed": len(observed),
        "missing": missing,
        "successful": sum(observed),
        "observed_rate": sum(observed) / len(observed) if observed else None,
        "missing_as_failure_rate": sum(observed) / planned if planned else None,
        "missing_as_success_rate": (
            (sum(observed) + missing) / planned if planned else None
        ),
    }


def paired_analysis(rows):
    by_key = {(row["team"], row["task_id"], row["condition"]): row for row in rows}
    teams = sorted({row["team"] for row in rows})
    effects = []
    discordant = {"board_only": 0, "control_only": 0}
    for team in teams:
        ids = sorted({row["task_id"] for row in rows if row["team"] == team})
        pairs = [tuple(
            binary_score(by_key[(team, task, arm)])
            if (team, task, arm) in by_key else None
            for arm in ("control", "board")
        ) for task in ids]
        complete = [(control, board) for control, board in pairs
                    if control is not None and board is not None]
        effects.append({
            "team": team, "complete_pairs": len(complete),
            "board_minus_control": (sum(board - control for control, board in complete) / len(complete)
                                    if complete else None),
        })
        discordant["board_only"] += sum(control == 0 and board == 1 for control, board in complete)
        discordant["control_only"] += sum(control == 1 and board == 0 for control, board in complete)
    values = [row["board_minus_control"] for row in effects if row["board_minus_control"] is not None]
    weights = [row["complete_pairs"] for row in effects if row["board_minus_control"] is not None]
    observed_signed = (sum(value * weight for value, weight in zip(values, weights)) / sum(weights)
                       if weights else None)
    observed = abs(observed_signed) if observed_signed is not None else None
    sign_flip = None
    if values and len(values) <= 20:
        statistics = [abs(sum(sign * value * weight for sign, value, weight in zip(signs, values, weights)) / sum(weights))
                      for signs in itertools.product((-1, 1), repeat=len(values))]
        sign_flip = sum(value >= observed - 1e-15 for value in statistics) / len(statistics)
    discordant_total = sum(discordant.values())
    mcnemar = None
    if discordant_total:
        low = min(discordant.values())
        mcnemar = min(1.0, 2 * sum(math.comb(discordant_total, k)
                                  for k in range(low + 1)) / (2 ** discordant_total))
    return {"team_effects": effects,
            "task_count_weighted_team_board_minus_control": observed_signed,
            "exact_team_sign_flip_p_two_sided": sign_flip,
            "task_pair_discordance": discordant,
            "descriptive_task_level_mcnemar_p_two_sided_not_cluster_valid": mcnemar}
