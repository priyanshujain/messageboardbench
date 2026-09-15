"""Fail-closed validation of no-model SWE readiness evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from messageboardbench.swe_validation import DATASET


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _local(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("validation paths must be repository-relative")
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("validation path escapes the repository")
    return path


def validate_environment_index(plan: Mapping[str, Any], root: Path) -> dict[str, Any]:
    """Validate exact per-task four-cell manifests before any paid request."""
    return validate_environment_index_for_records(plan, root, records=None)


def validate_environment_index_for_records(
    plan: Mapping[str, Any], root: Path,
    records: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Validate readiness evidence, optionally binding it to frozen record bytes."""
    declaration = plan.get("environment_validation")
    if not isinstance(declaration, dict) or declaration.get("required_before_execution") is not True:
        raise ValueError("plan does not require environment validation")
    index_path = _local(root, declaration.get("index_path"))
    index = json.loads(index_path.read_text())
    selected = list(plan.get("selection", {}).get("instance_ids", []))
    if (index.get("schema_version") != 1 or index.get("status") != "validated"
            or index.get("plan_sha256") != plan.get("plan_sha256")
            or index.get("dataset") != plan.get("dataset")
            or set(index.get("manifests", {})) != set(selected)):
        raise ValueError("environment validation index does not match the frozen plan")
    evidence = []
    expected_cells = {
        ("original", "nochange"): False,
        ("original", "oracle"): True,
        ("conflicting", "nochange"): False,
        ("conflicting", "oracle"): False,
    }
    for instance_id in selected:
        entry = index["manifests"][instance_id]
        manifest_path = _local(root, entry.get("path"))
        if _sha(manifest_path) != entry.get("sha256"):
            raise ValueError(f"validation manifest hash mismatch: {instance_id}")
        manifest = json.loads(manifest_path.read_text())
        if (manifest.get("schema_version") != 1
                or manifest.get("dataset") != DATASET
                or manifest.get("dataset_revision") != plan["dataset"]["revision"]
                or manifest.get("instance_id") != instance_id
                or manifest.get("network") != "none"):
            raise ValueError(f"validation manifest identity mismatch: {instance_id}")
        if records is not None:
            record = records.get(instance_id)
            if record is None:
                raise ValueError(f"frozen validation record missing: {instance_id}")
            canonical = hashlib.sha256(json.dumps(
                dict(record), sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest()
            expected_hashes = {
                "base_commit": record.get("base_commit"),
                "repo": record.get("repo"),
                "version": record.get("version"),
                "original_test_patch_sha256": hashlib.sha256(
                    str(record.get("original_test_patch", "")).encode()
                ).hexdigest(),
                "conflicting_test_patch_sha256": hashlib.sha256(
                    str(record.get("test_patch", "")).encode()
                ).hexdigest(),
                "oracle_patch_sha256": hashlib.sha256(
                    str(record.get("patch", "")).encode()
                ).hexdigest(),
            }
            if (canonical != plan.get("records_sha256", {}).get(instance_id)
                    or any(manifest.get(key) != value
                           for key, value in expected_hashes.items())):
                raise ValueError(f"validation patches do not match frozen record: {instance_id}")
        results = manifest.get("results")
        if not isinstance(results, list):
            raise ValueError(f"validation results missing: {instance_id}")
        cells = {(row.get("split"), row.get("mode")): row for row in results}
        if set(cells) != set(expected_cells) or len(results) != 4:
            raise ValueError(f"validation matrix incomplete: {instance_id}")
        identities = {(row.get("image_id"), tuple(row.get("repo_digests") or []))
                      for row in results}
        if len(identities) != 1 or any(
            cells[cell].get("resolved") is not expected
            for cell, expected in expected_cells.items()
        ):
            raise ValueError(f"validation matrix outcome mismatch: {instance_id}")
        if any(
            not row.get("target_statuses")
            or any(status in {"MISSING", "ERROR"}
                   for status in row["target_statuses"].values())
            for row in results
        ):
            raise ValueError(f"validation contains missing/error targets: {instance_id}")
        for row in results:
            output = manifest_path.parent / str(row.get("output_file", ""))
            if not output.is_file() or _sha(output) != row.get("output_sha256"):
                raise ValueError(f"validation output hash mismatch: {instance_id}")
        evidence.append({
            "instance_id": instance_id,
            "manifest_path": str(manifest_path),
            "manifest_sha256": entry["sha256"],
        })
    return {"index_path": str(index_path), "index_sha256": _sha(index_path),
            "validated_instances": evidence}
