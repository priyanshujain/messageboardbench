import runpy
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def test_verify_swe_population_script_imports_when_invoked_by_path_from_repo_root():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/analysis/verify_swe_population.py", "--help"],
        cwd=root, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--run" in result.stdout and "--export" in result.stdout


def test_board_operations_are_linked_to_board_episodes_without_condition_field():
    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(root / "scripts/analysis/verify_swe_population.py")
    board_operations_are_board_only = namespace["board_operations_are_board_only"]
    rows = [
        {"episode_id": "control-1", "condition": "control"},
        {"episode_id": "board-1", "condition": "board"},
    ]
    assert board_operations_are_board_only(rows, [{"episode_id": "board-1"}])
    assert not board_operations_are_board_only(rows, [{"episode_id": "control-1"}])
    assert not board_operations_are_board_only(rows, [{"episode_id": "unknown"}])


def test_enriched_environment_validation_is_compared_separately_from_plan_fields():
    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(root / "scripts/analysis/verify_swe_population.py")
    matches = namespace["manifest_matches_frozen_plan"]
    frozen = {
        "model": "openrouter/example",
        "environment_validation": {
            "index_path": "work/example/index.json",
            "required_before_execution": True,
        },
    }
    manifest = {
        "model": "openrouter/example",
        "environment_validation": {
            "index_path": str(root / "work/example/index.json"),
            "index_sha256": "abc",
            "validated_instances": [],
        },
    }

    assert matches(manifest, frozen)
    assert not matches({**manifest, "model": "openrouter/changed"}, frozen)


def test_environment_validation_uses_preserved_snapshot(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(root / "scripts/analysis/verify_swe_population.py")
    matches = namespace["environment_validation_matches_plan"]
    snapshot = tmp_path / "run/environment-validation"
    relative_manifest = Path("decisions/001-task/attempt-001/manifest.json")
    archived_manifest = snapshot / relative_manifest
    archived_manifest.parent.mkdir(parents=True)
    archived_manifest.write_text("{}\n")
    ledger_path = snapshot / "ledger.json"
    ledger_path.write_text("{}\n")

    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    frozen = {
        "dataset": {"path": "dataset", "revision": "revision", "split": "conflicting"},
        "plan_sha256": "plan-hash",
        "environment_validation": {
            "index_path": "work/example/index.json",
            "required_before_execution": True,
        },
        "selection": {
            "instance_ids": ["task"],
            "screening_ledger": {"file_sha256": digest(ledger_path)},
            "selected_manifest_sha256": {"task": digest(archived_manifest)},
        },
    }
    index_path = snapshot / "index.json"
    index_path.write_text(json.dumps({
        "schema_version": 1,
        "status": "validated",
        "plan_sha256": "plan-hash",
        "dataset": frozen["dataset"],
        "manifests": {
            "task": {
                "path": "work/example/" + relative_manifest.as_posix(),
                "sha256": digest(archived_manifest),
            }
        },
    }))
    manifest = {
        "environment_validation": {
            "index_path": "/unused/repository/work/example/index.json",
            "index_sha256": digest(index_path),
            "snapshot_path": str(snapshot),
            "validated_instances": [{
                "instance_id": "task",
                "manifest_path": "/unused/repository/work/example/" + relative_manifest.as_posix(),
                "manifest_sha256": digest(archived_manifest),
                "validated_image": "image",
                "validated_image_id": "image-id",
                "validated_image_ref": "repo-digest",
                "validated_repo_digest": "repo-digest",
            }],
        }
    }
    from messageboardbench import swe_prerequisites
    monkeypatch.setattr(swe_prerequisites, "validate_task_manifest", lambda *args, **kwargs: {
        "image": "image",
        "remote_image": {"id": "image-id", "repo_digests": ["repo-digest"],
                         "immutable_ref": "repo-digest"},
    })

    assert matches(manifest, frozen, tmp_path / "run")
    frozen["selection"]["selected_manifest_sha256"]["task"] = "wrong"
    assert not matches(manifest, frozen, tmp_path / "run")
    frozen["selection"]["selected_manifest_sha256"]["task"] = digest(archived_manifest)
    index_path.write_text(index_path.read_text() + "\n")
    assert not matches(manifest, frozen, tmp_path / "run")
