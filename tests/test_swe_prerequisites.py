from __future__ import annotations

import hashlib
import json

import pytest

from messageboardbench.swe_validation import ValidationError
from messageboardbench.swe_prerequisites import (
    validate_environment_index,
    validate_environment_index_for_records,
    validate_task_manifest,
)
from scripts.validate_swe_population_prerequisites import (
    load_selected_pairs,
    pull_image_once,
    require_resolved_targets,
    validate_existing_manifests,
)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path):
    output_hashes = {}
    cells = []
    expected = {
        ("original", "nochange"): False,
        ("original", "oracle"): True,
        ("conflicting", "nochange"): False,
        ("conflicting", "oracle"): False,
    }
    for split, mode in expected:
        name = f"{split}-{mode}.txt"
        output_hashes[name] = write(tmp_path / "evidence" / name, "test output")
        cells.append({"split": split, "mode": mode, "resolved": expected[split, mode],
                      "image": "repo:tag", "test_command": ["pytest"],
                      "image_id": "sha256:image", "repo_digests": ["repo@sha256:digest"],
                      "target_statuses": {"target": "PASSED" if expected[split, mode] else "FAILED"},
                      "output_file": name, "output_sha256": output_hashes[name]})
    record = {"instance_id": "task", "base_commit": "base", "repo": "org/repo",
              "version": "1", "original_test_patch": "original", "test_patch": "conflict",
              "patch": "oracle"}
    manifest = {"schema_version": 1, "dataset": "fjzzq2002/impossible_swebench",
                "dataset_revision": "1" * 40, "instance_id": "task", "network": "none",
                "image": "repo:tag",
                "remote_image": {"id": "sha256:image",
                                 "repo_digests": ["repo@sha256:digest"]},
                "test_command": ["pytest"],
                "base_commit": "base", "repo": "org/repo", "version": "1",
                "original_test_patch_sha256": hashlib.sha256(b"original").hexdigest(),
                "conflicting_test_patch_sha256": hashlib.sha256(b"conflict").hexdigest(),
                "oracle_patch_sha256": hashlib.sha256(b"oracle").hexdigest(), "results": cells}
    manifest_path = tmp_path / "evidence" / "manifest.json"
    manifest_hash = write(manifest_path, manifest)
    canonical = hashlib.sha256(json.dumps(
        record, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    plan = {"plan_sha256": "plan", "records_sha256": {"task": canonical}, "dataset": {
                "path": "fjzzq2002/impossible_swebench", "revision": "1" * 40,
                "split": "conflicting"},
            "selection": {"instance_ids": ["task"]},
            "environment_validation": {"required_before_execution": True,
                                       "index_path": "index.json"}}
    index = {"schema_version": 1, "status": "validated", "plan_sha256": "plan",
             "dataset": plan["dataset"], "manifests": {
                 "task": {"path": "evidence/manifest.json", "sha256": manifest_hash}}}
    write(tmp_path / "index.json", index)
    return plan, manifest_path, record


def test_environment_index_requires_complete_nonmissing_hashed_evidence(tmp_path):
    plan, manifest_path, record = fixture(tmp_path)
    result = validate_environment_index_for_records(plan, tmp_path, {"task": record})
    assert len(result["validated_instances"]) == 1
    manifest = json.loads(manifest_path.read_text())
    manifest["results"][0]["target_statuses"] = {"target": "MISSING"}
    write(manifest_path, manifest)
    index_path = tmp_path / "index.json"
    index = json.loads(index_path.read_text())
    index["manifests"]["task"]["sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    write(index_path, index)
    with pytest.raises(ValueError, match="missing/error targets"):
        validate_environment_index(plan, tmp_path)


def test_environment_index_is_required_and_plan_bound(tmp_path):
    plan, _, _ = fixture(tmp_path)
    plan["plan_sha256"] = "different"
    with pytest.raises(ValueError, match="does not match"):
        validate_environment_index(plan, tmp_path)


def test_unresolved_cell_requires_an_actual_failed_target(tmp_path):
    plan, manifest_path, record = fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["results"][0]["target_statuses"] = {"target": "PASSED"}
    write(manifest_path, manifest)
    index_path = tmp_path / "index.json"
    index = json.loads(index_path.read_text())
    index["manifests"]["task"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    write(index_path, index)
    with pytest.raises(ValueError, match="lacks a failed target"):
        validate_environment_index_for_records(plan, tmp_path, {"task": record})


def test_environment_manifest_patch_hashes_are_bound_to_frozen_record(tmp_path):
    plan, _, record = fixture(tmp_path)
    changed = {**record, "test_patch": "different"}
    with pytest.raises(ValueError, match="frozen record"):
        validate_environment_index_for_records(plan, tmp_path, {"task": changed})


def test_image_is_pulled_once_before_any_inspection_or_trial():
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return __import__("subprocess").CompletedProcess(argv, 0, "pulled", "")

    pulled = set()
    pull_image_once("image:tag", pulled, {"DOCKER_HOST": "remote"}, run=run)
    calls.append(["docker", "image", "inspect", "image:tag"])
    pull_image_once("image:tag", pulled, {"DOCKER_HOST": "remote"}, run=run)
    assert calls == [
        ["docker", "pull", "image:tag"],
        ["docker", "image", "inspect", "image:tag"],
    ]


def test_selected_pairs_load_each_dataset_split_exactly_once():
    calls = []
    common = {
        "instance_id": "task", "repo": "org/repo", "version": "1",
        "base_commit": "base", "patch": "oracle", "original_test_patch": "original",
        "FAIL_TO_PASS": ["target"], "PASS_TO_PASS": [],
    }
    rows = {
        "original": {"task": {**common, "test_patch": "original"}},
        "conflicting": {"task": {**common, "test_patch": "conflict"}},
    }

    def loader(revision, split):
        calls.append((revision, split))
        return rows[split]

    plan = {"dataset": {"revision": "1" * 40},
            "selection": {"instance_ids": ["task"]}}
    pairs, conflicting = load_selected_pairs(plan, loader=loader)
    assert calls == [("1" * 40, "original"), ("1" * 40, "conflicting")]
    assert pairs["task"] == (rows["original"]["task"], rows["conflicting"]["task"])
    assert conflicting is rows["conflicting"]


def test_new_cell_rejects_missing_targets_immediately():
    result = __import__("types").SimpleNamespace(
        split="conflicting", mode="oracle", target_statuses={"target": "MISSING"}
    )
    with pytest.raises(ValidationError, match="missing/error targets.*conflicting/oracle"):
        require_resolved_targets("task", result)


def test_resume_rejects_existing_missing_manifest_before_reuse(tmp_path):
    plan, manifest_path, record = fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["results"][0]["target_statuses"] = {"target": "ERROR"}
    task_dir = tmp_path / "task"
    for row in manifest["results"]:
        write(task_dir / row["output_file"], "test output")
    write(task_dir / "manifest.json", manifest)
    with pytest.raises(ValueError, match="missing/error targets"):
        validate_existing_manifests(plan, tmp_path, {"task": record})
