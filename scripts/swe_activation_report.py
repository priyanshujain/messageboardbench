"""Generate the automatic, unreviewed two-model SWE board activation report."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from inspect_ai.log import read_eval_log

if __package__:
    from .board_report import generate_report
else:
    from board_report import generate_report


def summary(rows: list[dict], planned: int, operations: list[dict], edges: list[dict], later_edges: list[dict]) -> dict:
    observed = [row for row in rows if row.get("score") is not None]
    return {
        "planned": planned,
        "terminal": len(rows),
        "observed": len(observed),
        "scorer_passes": sum(row.get("score") in {1, 1.0, "C"} for row in observed),
        "errors": sum(row.get("error") is not None for row in rows),
        "publishing_episodes": sum(bool(row.get("published_post_ids")) for row in rows),
        "model_issued_read_events": sum(row.get("board_read_events", 0) for row in rows),
        "host_audited_reads": len(operations),
        "delivered_read_episodes": len({row["episode_id"] for row in operations if row.get("delivery_confirmed")}),
        "invalid_reads": sum(not row.get("success") for row in operations),
        "peer_receiving_episodes": len({edge["reader_episode_id"] for edge in edges}),
        "peer_receipt_edges": len(edges),
        "later_peer_receiving_episodes": len({edge["reader_episode_id"] for edge in later_edges}),
        "later_peer_receipt_edges": len(later_edges),
        "activation_gate_later_peer_receipt": bool(later_edges),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    generate_report(args.run, args.out)
    rows = json.loads((args.out / "episodes.json").read_text())
    operations = json.loads((args.out / "board-operations.json").read_text())
    edges = json.loads((args.out / "exposure-edges.json").read_text())
    posts = json.loads((args.out / "public-posts.json").read_text())
    for row in rows:
        log = read_eval_log(row["log_path"], resolve_attachments=True)
        sample = next(sample for sample in log.samples or [] if sample.uuid == row["sample_uuid"])
        row["board_read_events"] = sum(event.event == "tool" and event.function == "read_messages" for event in sample.events)
    manifest = json.loads((args.run / "manifest.json").read_text())
    models = list(manifest["models_by_team"].values())
    planned = manifest["instance_count"]
    cohort_by_episode = {row["episode_id"]: row["cohort"] for row in rows}
    later_edges = [edge for edge in edges if cohort_by_episode.get(edge["author_episode_id"], 99) < cohort_by_episode.get(edge["reader_episode_id"], -1)]
    by_model = {}
    for model in models:
        model_rows = [row for row in rows if row["model"] == model]
        ids = {row["episode_id"] for row in model_rows}
        model_operations = [row for row in operations if row["episode_id"] in ids and row["operation"] == "read_messages"]
        model_edges = [edge for edge in edges if edge["reader_episode_id"] in ids]
        model_later_edges = [edge for edge in later_edges if edge["reader_episode_id"] in ids]
        by_model[model] = summary(model_rows, planned, model_operations, model_edges, model_later_edges)
    report = {
        "automatic_unreviewed": True,
        "purpose": "communication activation diagnostic; no control arm or causal effect estimate",
        "by_model": by_model,
        "communication": {
            "posts": len(posts),
            "reading_episodes": len({row["episode_id"] for row in operations
                                     if row["operation"] == "read_messages"}),
            "peer_receiving_episodes": len({row["reader_episode_id"] for row in edges}),
            "peer_receipt_edges": len(edges),
        },
        "activation_gate": {
            "any_substantive_post": "requires behavioral review",
            "any_later_peer_receipt": bool(later_edges),
            "later_peer_receipt_edges": len(later_edges),
        },
        "limitations": [
            "This board-only diagnostic cannot estimate whether board access changes cheating.",
            "Posts and receipts are automatic structural measures; substance and adoption require review.",
            "Each model has one evolving board history, so this run does not establish repeatability.",
            "A scorer pass on a contradictory evaluator is not an automatic behavioral label.",
        ],
    }
    source_dir = args.out / "postprocess-source-snapshot"
    source_dir.mkdir()
    report["postprocess_source_snapshot"] = []
    for source in (Path(__file__).resolve(), Path(__file__).with_name("board_report.py")):
        archived = source_dir / source.name
        shutil.copyfile(source, archived)
        report["postprocess_source_snapshot"].append({
            "source": str(source), "archived": str(archived.relative_to(args.out)),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        })
    (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = [
        "# Automatic SWE board activation report", "",
        "This report is deterministic and unreviewed. It does not infer cheating, adoption, or intent.", "",
        "| Model | Terminal / planned | Scorer passes | Publishing episodes | Delivered-read episodes | Peer-receiving episodes |", "|---|---:|---:|---:|---:|---:|",
    ]
    for model, values in by_model.items():
        lines.append(
            f"| {model} | {values['terminal']} / {values['planned']} | {values['scorer_passes']} | "
            f"{values['publishing_episodes']} | {values['delivered_read_episodes']} | {values['peer_receiving_episodes']} |"
        )
    lines += ["", f"Posts: {len(posts)}. Peer receipt edges: {len(edges)}.", "",
              "This diagnostic has no no-board control and makes no causal or repeatability claim.", ""]
    (args.out / "REPORT.md").write_text("\n".join(lines))
    print(json.dumps(by_model, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
