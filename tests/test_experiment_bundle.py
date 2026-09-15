import json
from pathlib import Path
import subprocess

import pytest

from messageboardbench.experiment_bundle import (
    REMOTE_DOCKER_HOST,
    manifest_sha256,
    run_bundle,
    validate_manifest,
)


def script(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# offline fixture\n")


def ready_manifest(root: Path) -> dict:
    for name in (
        "scripts/fake_runner.py",
        "scripts/board_report.py",
        "scripts/analysis/validate_board_export.py",
        "scripts/analysis/board_resources.py",
        "scripts/remote_docker.py",
    ):
        script(root, name)
    manifest = {
        "schema_version": 1,
        "status": "ready",
        "experiment_id": "fixture",
        "remote_docker_host": REMOTE_DOCKER_HOST,
        "blockers": [],
        "outputs": {
            "run_dir": "logs/fixture/run",
            "report_dir": "logs/fixture/report",
            "verification_file": "logs/fixture/verification.json",
            "resource_file": "logs/fixture/resources.json",
            "state_file": "logs/fixture-status.json",
        },
        "execution": {
            "argv": [".venv/bin/python", "scripts/fake_runner.py", "--out", "logs/fixture/run", "--execute"]
        },
        "postprocess": [
            {
                "name": "report",
                "requires": ["logs/fixture/run/manifest.json"],
                "argv": [".venv/bin/python", "scripts/board_report.py", "--run", "logs/fixture/run", "--out", "logs/fixture/report"],
            },
            {
                "name": "verify",
                "requires": ["logs/fixture/report/manifest.json"],
                "argv": [".venv/bin/python", "scripts/analysis/validate_board_export.py", "--run", "logs/fixture/run", "--export", "logs/fixture/report", "--out", "logs/fixture/verification.json"],
            },
            {
                "name": "resources",
                "requires": ["logs/fixture/report/episodes.json"],
                "argv": [".venv/bin/python", "scripts/analysis/board_resources.py", "--run", "logs/fixture/run", "--export", "logs/fixture/report", "--out", "logs/fixture/resources.json"],
            },
        ],
    }
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    return manifest


def test_draft_fails_before_command_validation(tmp_path):
    manifest = {"schema_version": 1, "status": "draft", "blockers": ["not frozen"]}
    with pytest.raises(ValueError, match="not frozen"):
        validate_manifest(manifest, tmp_path)


def test_ready_manifest_rejects_hash_mutation_and_nonremote_host(tmp_path):
    manifest = ready_manifest(tmp_path)
    validate_manifest(manifest, tmp_path)
    manifest["experiment_id"] = "mutated"
    with pytest.raises(ValueError, match="self-hash"):
        validate_manifest(manifest, tmp_path)
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    manifest["remote_docker_host"] = "unix:///var/run/docker.sock"
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    with pytest.raises(ValueError, match="remote_docker_host"):
        validate_manifest(manifest, tmp_path)


def test_nonzero_execution_still_runs_safe_available_postprocessing(tmp_path):
    manifest = ready_manifest(tmp_path)
    manifest_path = tmp_path / "experiment.json"
    manifest_path.write_text(json.dumps(manifest))
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if len(calls) == 1:
            run_dir = tmp_path / "logs/fixture/run"
            run_dir.mkdir(parents=True)
            (run_dir / "manifest.json").write_text("{}")
            return subprocess.CompletedProcess(argv, 9)
        if len(calls) == 2:
            report_dir = tmp_path / "logs/fixture/report"
            report_dir.mkdir(parents=True)
            (report_dir / "manifest.json").write_text("{}")
            (report_dir / "episodes.json").write_text("[]")
        return subprocess.CompletedProcess(argv, 0)

    assert run_bundle(manifest_path, tmp_path, run=fake_run) == 9
    assert calls[0][:3] == [".venv/bin/python", "scripts/remote_docker.py", "--"]
    assert [call[1] for call in calls[1:]] == [
        "scripts/board_report.py", "scripts/analysis/validate_board_export.py",
        "scripts/analysis/board_resources.py",
    ]
    status = json.loads((tmp_path / "logs/fixture-status.json").read_text())
    assert status["status"] == "partial"
    assert status["execution"]["returncode"] == 9
    assert [step["status"] for step in status["postprocess"]] == ["completed", "completed", "completed"]


def test_missing_postprocess_input_is_recorded_without_running_step(tmp_path):
    manifest = ready_manifest(tmp_path)
    manifest_path = tmp_path / "experiment.json"
    manifest_path.write_text(json.dumps(manifest))
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 4)

    assert run_bundle(manifest_path, tmp_path, run=fake_run) == 4
    assert len(calls) == 1
    status = json.loads((tmp_path / "logs/fixture-status.json").read_text())
    assert status["status"] == "partial"
    assert [step["status"] for step in status["postprocess"]] == ["skipped", "skipped", "skipped"]


def test_existing_state_refuses_a_second_start_before_execution(tmp_path):
    manifest = ready_manifest(tmp_path)
    manifest_path = tmp_path / "experiment.json"
    manifest_path.write_text(json.dumps(manifest))
    state = tmp_path / "logs/fixture-status.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"status":"running"}\n')
    calls = []
    with pytest.raises(ValueError, match="fresh output already exists"):
        run_bundle(manifest_path, tmp_path, run=lambda *args, **kwargs: calls.append(args))
    assert calls == []


def test_resumable_bundle_archives_derived_outputs_before_restart(tmp_path):
    manifest = ready_manifest(tmp_path)
    manifest["execution"]["resume"] = True
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    manifest_path = tmp_path / "experiment.json"
    manifest_path.write_text(json.dumps(manifest))
    run_dir = tmp_path / "logs/fixture/run"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text("{}")
    report = tmp_path / "logs/fixture/report"
    report.mkdir(parents=True)
    (report / "old.txt").write_text("old")
    state = tmp_path / "logs/fixture-status.json"
    state.write_text(json.dumps({"experiment_id": "fixture", "status": "partial", "resume_count": 0}))

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 7)

    assert run_bundle(manifest_path, tmp_path, run=fake_run) == 7
    archived = tmp_path / "logs/fixture/resume-history/attempt-1/report/old.txt"
    assert archived.read_text() == "old"
    status = json.loads(state.read_text())
    assert status["resume_count"] == 1
