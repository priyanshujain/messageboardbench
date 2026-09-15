"""Pure deterministic statistics shared by SWE reporting and verification."""
from __future__ import annotations

import itertools
import math


def binary_score(row):
    score = row.get("score")
    return 1 if score in (1, 1.0, "C") else 0 if score is not None else None


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
