from __future__ import annotations

import hashlib
import json

import pytest

from messageboardbench.swe_prerequisites import (
    validate_environment_index,
    validate_environment_index_for_records,
)
from scripts.validate_swe_population_prerequisites import pull_image_once


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
                      "image_id": "sha256:image", "repo_digests": ["repo@sha256:digest"],
                      "target_statuses": {"target": "PASSED" if mode == "oracle" else "FAILED"},
                      "output_file": name, "output_sha256": output_hashes[name]})
    record = {"instance_id": "task", "base_commit": "base", "repo": "org/repo",
              "version": "1", "original_test_patch": "original", "test_patch": "conflict",
              "patch": "oracle"}
    manifest = {"schema_version": 1, "dataset": "fjzzq2002/impossible_swebench",
                "dataset_revision": "1" * 40, "instance_id": "task", "network": "none",
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
