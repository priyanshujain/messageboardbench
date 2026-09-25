#!/usr/bin/env python3
"""Regenerate the reviewed SWE shared-board SVG figures."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
METRICS = HERE.parent
MODELS = [
    ("openrouter/z-ai/glm-5.3-flash", "GLM", "#31688e"),
    ("openrouter/meta/muse-spark-1.3-contributor", "Muse", "#b05a2a"),
    ("openrouter/deepseek/deepseek-v4-pro-0813", "DeepSeek", "#438a5e"),
]

with (METRICS / "summary.csv").open() as handle:
    SUMMARY = list(csv.DictReader(handle))
with (METRICS / "events.csv").open() as handle:
    EVENTS = list(csv.DictReader(handle))


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def find(model: str, family: str, metric: str, category: str | None = None):
    for row in SUMMARY:
        if row["model"] == model and row["metric_family"] == family and row["metric_name"] == metric:
            if category is None or row["category"] == category:
                return row
    return None


def bar_figure(filename: str, title: str, family: str, metrics: list[tuple[str, str]], note: str = "") -> None:
    width = 1120
    height = 100 + 66 * len(metrics) + (24 if note else 0)
    left = 285
    plot_width = 690
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="20" y="30" font-family="sans-serif" font-size="19" font-weight="bold">{esc(title)}</text>',
    ]
    for i, (metric, label) in enumerate(metrics):
        y = 58 + i * 66
        lines.append(f'<text x="12" y="{y + 24}" font-family="sans-serif" font-size="12">{esc(label)}</text>')
        for j, (model, short, color) in enumerate(MODELS):
            row = find(model, family, metric)
            yy = y + j * 15
            if not row or row["value"] == "":
                text = f"{short} unknown"
                lines.append(f'<text x="{left}" y="{yy + 10}" font-family="sans-serif" font-size="10" fill="#666">{text}</text>')
                continue
            value = max(0.0, min(1.0, float(row["value"])))
            length = plot_width * value
            n = row["numerator"]
            d = row["denominator"]
            text = f"{short} {n}/{d}" if n != "" and d != "" else f"{short} {float(row['value']):.3f}"
            lines.append(f'<rect x="{left}" y="{yy}" width="{length:.1f}" height="11" fill="{color}"/>')
            lines.append(f'<text x="{left + length + 6:.1f}" y="{yy + 10}" font-family="sans-serif" font-size="10">{esc(text)}</text>')
    if note:
        lines.append(f'<text x="12" y="{height - 12}" font-family="sans-serif" font-size="10" fill="#555">{esc(note)}</text>')
    lines.append("</svg>")
    (HERE / filename).write_text("\n".join(lines) + "\n")


bar_figure(
    "progression-funnel.svg", "Reviewed cheating progression", "cheating_progression",
    [("cheating_considered", "considered"), ("cheating_attempted", "attempted"),
     ("cheating_retained", "retained"), ("cheating_successful", "successful")],
    "Denominators follow behavior, artifact, and fresh-grader eligibility.",
)
bar_figure(
    "pressure-timeline.svg", "Persistence after contradiction recognition", "persistence_pressure",
    [("continuation_after_recognition", "continued cheating behavior"), ("safe_exit", "safe exit")],
    "GLM and Muse decision-share annotation remains unknown; no value is imputed.",
)
bar_figure(
    "transmission-funnel.svg", "Board transmission outcomes", "information_governance",
    [("channel_activation", "read or post activation"), ("exact_peer_recipient", "exact peer recipient"),
     ("candidate_unattributed_adoption", "candidate unattributed adoption"),
     ("attributed_adoption", "attributed adoption")],
    "Each model has one dependent board history. Candidate adoption is not attributed transmission.",
)
bar_figure(
    "governance-response.svg", "Governance and disclosure", "information_governance",
    [("peer_warning", "peer warning"), ("public_exploit_publication", "public exploit publication"),
     ("final_answer_disclosure", "final-answer disclosure"),
     ("success_claim_artifact_conflict", "success claim and artifact conflict")],
)
bar_figure(
    "cot-observability.svg", "Reasoning observability", "cot_observability",
    [("reasoning_message_coverage", "nonempty reasoning field"),
     ("readable_reasoning_message_coverage", "readable reasoning field"),
     ("episode_with_unresolved_behavioral_label", "episode with unresolved label")],
    "Muse reasoning objects are encrypted or redacted, so readable coverage is zero.",
)

mechanisms = [
    "literal_special_case", "call_history_or_cache", "protocol_or_equality_spoof",
    "global_runtime_mutation", "protected_test_edit", "test_runner_evaluator_or_grader_interference",
]
scopes = ["narrow", "object_api", "package", "process_global", "evaluation_pipeline", "external_system"]
counts = Counter(
    (row["model"], row["mechanism"], row["scope"])
    for row in EVENTS if row["event_type"] == "mechanism_attempt" and row.get("mechanism")
)
width = 1140
height = 135 + 40 * len(mechanisms)
lines = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
    '<rect width="100%" height="100%" fill="white"/>',
    '<text x="20" y="30" font-family="sans-serif" font-size="19" font-weight="bold">Attempted mechanism by scope</text>',
]
for j, scope in enumerate(scopes):
    lines.append(f'<text x="{410 + 115*j}" y="62" font-family="sans-serif" font-size="10">{esc(scope.replace("_", " "))}</text>')
for i, mechanism in enumerate(mechanisms):
    y = 78 + 40 * i
    lines.append(f'<text x="12" y="{y + 19}" font-family="sans-serif" font-size="11">{esc(mechanism.replace("_", " "))}</text>')
    for j, scope in enumerate(scopes):
        values = [counts[(model, mechanism, scope)] for model, _, _ in MODELS]
        total = sum(values)
        fill = "#e9eef2" if total == 0 else "#88aeca"
        x = 405 + 115*j
        lines.append(f'<rect x="{x}" y="{y}" width="102" height="27" fill="{fill}"/>')
        lines.append(f'<text x="{x + 7}" y="{y + 18}" font-family="sans-serif" font-size="10">{values[0]}/{values[1]}/{values[2]}</text>')
lines.append(f'<text x="405" y="{height - 15}" font-family="sans-serif" font-size="10" fill="#555">Cells show GLM/Muse/DeepSeek event counts.</text>')
lines.append("</svg>")
(HERE / "mechanism-scope.svg").write_text("\n".join(lines) + "\n")

print("wrote 6 SVG figures")
