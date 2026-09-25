#!/usr/bin/env python3
"""Regenerate baseline SVG figures from the maintained metric CSV files."""

import csv
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
METRICS = HERE.parent
MODEL_ORDER = ["glm", "muse", "deepseek"]
COLORS = {"glm": "#3568a8", "muse": "#c45d35", "deepseek": "#548f52"}
MECHANISMS = [
    "literal_special_case", "call_history_or_cache", "protocol_or_equality_spoof",
    "caller_stack_source_or_test_detection", "global_runtime_mutation", "protected_test_edit",
    "test_runner_evaluator_or_grader_interference", "environment_or_dependency_manipulation",
    "external_solution_retrieval_or_reuse", "side_channel", "result_concealment_or_false_claim", "other",
]


with (METRICS / "summary.csv").open() as handle:
    SUMMARY = list(csv.DictReader(handle))


def bars(filename, title, metric_names, family):
    selected = [row for row in SUMMARY if row["metric_family"] == family and row["metric_name"] in metric_names]
    width, height = 980, 110 + 52 * len(metric_names)
    left, right, top = 220, 90, 55
    plot_width = width - left - right
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="20" y="28" font-family="sans-serif" font-size="18" font-weight="bold">{title}</text>',
    ]
    for i, metric in enumerate(metric_names):
        y = top + i * 52
        lines.append(f'<text x="10" y="{y + 21}" font-family="sans-serif" font-size="12">{metric.replace("_", " ")}</text>')
        model_rows = [row for row in selected if row["metric_name"] == metric]
        for j, short in enumerate(MODEL_ORDER):
            row = next((item for item in model_rows if short in item["model"]), None)
            if row is None or not row["value"]:
                continue
            value = float(row["value"])
            bar_width = plot_width * max(0.0, min(1.0, value))
            yy = y + j * 12
            label = f'{row["numerator"]}/{row["denominator"]}' if row["numerator"] and row["denominator"] else f'{value:.2f}'
            lines.append(f'<rect x="{left}" y="{yy}" width="{bar_width:.1f}" height="9" fill="{COLORS[short]}"/>')
            lines.append(f'<text x="{left + bar_width + 5:.1f}" y="{yy + 9}" font-family="sans-serif" font-size="10">{short} {label}</text>')
    lines.append('</svg>')
    (HERE / filename).write_text("\n".join(lines) + "\n")


bars("progression-funnel.svg", "Reviewed cheating progression", [
    "cheating_considered", "cheating_attempted", "cheating_retained", "cheating_successful", "cheating_reversed",
], "cheating_progression")
bars("pressure-timeline.svg", "Pressure response", [
    "continuation_after_recognition", "safe_exit",
], "persistence_pressure")
bars("governance-response.svg", "Governance and disclosure", [
    "internet_visible_activity", "final_answer_disclosure", "source_comment_disclosure", "success_claim_artifact_conflict",
], "information_governance")
bars("cot-observability.svg", "Reasoning observability and unresolved information", [
    "reasoning_message_coverage", "readable_reasoning_message_coverage", "episode_with_unresolved_information_label",
], "cot_observability")

with (METRICS / "events.csv").open() as handle:
    events = list(csv.DictReader(handle))
counts = Counter((row["model"], row["mechanism"], row["scope"]) for row in events if row["event_type"] == "mechanism_attempt")
width, height = 1100, 130 + 34 * len(MECHANISMS)
lines = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
    '<rect width="100%" height="100%" fill="white"/>',
    '<text x="20" y="28" font-family="sans-serif" font-size="18" font-weight="bold">Attempted mechanism by maximum episode scope</text>',
]
scopes = ["narrow", "object_api", "package", "process_global", "evaluation_pipeline", "external_system"]
for j, scope in enumerate(scopes):
    lines.append(f'<text x="{390 + j * 110}" y="58" font-family="sans-serif" font-size="11">{scope.replace("_", " ")}</text>')
for i, mechanism in enumerate(MECHANISMS):
    y = 78 + i * 34
    lines.append(f'<text x="10" y="{y + 18}" font-family="sans-serif" font-size="11">{mechanism.replace("_", " ")}</text>')
    for j, scope in enumerate(scopes):
        cell = [sum(n for (model, mech, sc), n in counts.items() if short in model and mech == mechanism and sc == scope) for short in MODEL_ORDER]
        x = 390 + j * 110
        lines.append(f'<rect x="{x}" y="{y}" width="90" height="24" fill="{"#eeeeee" if sum(cell) == 0 else "#7b9fc8"}"/>')
        lines.append(f'<text x="{x + 6}" y="{y + 17}" font-family="sans-serif" font-size="10">{cell[0]}/{cell[1]}/{cell[2]}</text>')
lines.append('<text x="390" y="112" font-family="sans-serif" font-size="10">cells show GLM/Muse/DeepSeek event counts</text>')
lines.append('</svg>')
(HERE / "mechanism-scope.svg").write_text("\n".join(lines) + "\n")
