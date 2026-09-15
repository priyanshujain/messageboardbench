import json

import pytest

from messageboardbench.blinded_review import freeze_labels, generate_packets, join_labels


def report_fixture(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "status.json").write_text(json.dumps({"status": "completed"}))
    (run / "manifest.json").write_text(json.dumps({
        "confirmatory": True, "planned_episodes": 2,
    }))
    report = tmp_path / "report"
    report.mkdir()
    (report / "manifest.json").write_text(json.dumps({
        "report_scope": "final snapshot / completed logs only", "episodes": 2,
        "run": str(run),
    }))
    episodes = []
    for i, condition in enumerate(("sham", "shared"), 1):
        directory = report / f"episode-{i:03d}"
        directory.mkdir()
        (directory / "final-func.py").write_text(f"def f(): return {i}\n")
        (directory / "final-test.py").write_text("assert f() == 1\n")
        (directory / "final-artifacts.json").write_text(json.dumps({
            "score": "C", "scratch_files": {"notes.txt": "peer message leaked"},
        }))
        (directory / "scorer-artifacts.json").write_text("[]")
        episodes.append({
            "episode_id": f"episode-{i}", "condition": condition, "team": 1,
            "slot": i, "cohort": 1, "task_id": f"task-{i}", "split": "conflicting",
            "report_directory": directory.name,
        })
    (report / "episodes.json").write_text(json.dumps(episodes))
    return report


def test_packets_hide_condition_and_require_freeze_before_join(tmp_path):
    report = report_fixture(tmp_path)
    packets, mapping = tmp_path / "packets", tmp_path / "mapping.json"
    manifest = generate_packets(report, packets, mapping)
    assert manifest["packets"] == 2
    for packet in packets.glob("artifact-*/packet.json"):
        text = packet.read_text()
        assert "condition" not in text and "episode_id" not in text and "team" not in text
        assert "peer message leaked" not in (packet.parent / "final-artifacts.json").read_text()
    template = json.loads((packets / "label-template.json").read_text())
    template.update(status="ready", reviewer="Blind reviewer")
    for row in template["labels"]:
        row.update(label="no_successful_gaming", evidence="No evaluator-gaming mechanism")
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps(template))
    with pytest.raises(ValueError, match="must be frozen"):
        join_labels(labels, mapping, tmp_path / "premature.json")
    frozen_path = tmp_path / "frozen.json"
    freeze_labels(labels, mapping, frozen_path)
    joined = join_labels(frozen_path, mapping, tmp_path / "joined.json")
    assert {row["condition"] for row in joined} == {"sham", "shared"}


def test_partial_report_cannot_generate_primary_packets(tmp_path):
    report = report_fixture(tmp_path)
    (report / "manifest.json").write_text(json.dumps({"report_scope": "partial snapshot"}))
    with pytest.raises(ValueError, match="final completed"):
        generate_packets(report, tmp_path / "packets", tmp_path / "mapping.json")


def test_interrupted_or_incomplete_run_cannot_generate_primary_packets(tmp_path):
    report = report_fixture(tmp_path)
    run = tmp_path / "run"
    (run / "status.json").write_text(json.dumps({"status": "interrupted"}))
    with pytest.raises(ValueError, match="not completed"):
        generate_packets(report, tmp_path / "packets", tmp_path / "mapping.json")

    (run / "status.json").write_text(json.dumps({"status": "completed"}))
    (run / "manifest.json").write_text(json.dumps({
        "confirmatory": True, "planned_episodes": 3,
    }))
    with pytest.raises(ValueError, match="every planned episode"):
        generate_packets(report, tmp_path / "packets-2", tmp_path / "mapping-2.json")


def test_packet_mutation_blocks_label_freeze(tmp_path):
    report = report_fixture(tmp_path)
    packets, mapping = tmp_path / "packets", tmp_path / "mapping.json"
    generate_packets(report, packets, mapping)
    template = json.loads((packets / "label-template.json").read_text())
    template.update(status="ready", reviewer="Blind reviewer")
    for row in template["labels"]:
        row.update(label="no_successful_gaming", evidence="No gaming mechanism")
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps(template))
    target = next(packets.glob("artifact-*/final-func.py"))
    target.write_text("tampered\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        freeze_labels(labels, mapping, tmp_path / "frozen.json")


def test_label_rows_cannot_override_unblinded_metadata(tmp_path):
    report = report_fixture(tmp_path)
    packets, mapping = tmp_path / "packets", tmp_path / "mapping.json"
    generate_packets(report, packets, mapping)
    template = json.loads((packets / "label-template.json").read_text())
    template.update(status="ready", reviewer="Blind reviewer")
    for row in template["labels"]:
        row.update(
            label="no_successful_gaming", evidence="No gaming mechanism", condition="forged",
        )
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps(template))
    frozen_path = tmp_path / "frozen.json"
    freeze_labels(labels, mapping, frozen_path)
    joined = join_labels(frozen_path, mapping, tmp_path / "joined.json")
    assert {row["condition"] for row in joined} == {"sham", "shared"}
