"""Build or validate the no-model SWE readiness index for a frozen pilot."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from messageboardbench.swe_board import load_records, plan_hash
from messageboardbench.swe_prerequisites import (
    validate_environment_index_for_records,
    validate_task_manifest,
)
from messageboardbench.swe_validation import (
    GRADER_ENVIRONMENT,
    ValidationError,
    docker_preflight,
    manifest as trial_manifest,
    run_trial,
    swebench_spec,
    validate_expected_matrix,
    validate_pair,
)


ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pull_image_once(image: str, pulled: set[str], environ, run=subprocess.run) -> None:
    """Pull an exact image tag once before run_trial tries to inspect it."""
    if image in pulled:
        return
    result = run(["docker", "pull", image], env=dict(environ), text=True,
                 capture_output=True)
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise ValidationError(f"image pull failed for {image}: {detail}")
    pulled.add(image)


def load_selected_pairs(plan, loader=None):
    """Load each pinned dataset split once, then validate all selected pairs."""
    loader = load_records if loader is None else loader
    revision = plan["dataset"]["revision"]
    original_records = loader(revision, "original")
    conflicting_records = loader(revision, "conflicting")
    pairs = {}
    for instance_id in plan["selection"]["instance_ids"]:
        try:
            original = original_records[instance_id]
            conflicting = conflicting_records[instance_id]
        except KeyError as exc:
            raise ValidationError(
                f"selected task is absent from a pinned dataset split: {instance_id}"
            ) from exc
        validate_pair(original, conflicting)
        pairs[instance_id] = (original, conflicting)
    return pairs, conflicting_records


def require_resolved_targets(instance_id: str, result) -> None:
    """Reject an unusable validation cell before another cell is run."""
    statuses = result.target_statuses
    if not statuses or any(status in {"MISSING", "ERROR"} for status in statuses.values()):
        raise ValidationError(
            f"validation contains missing/error targets: {instance_id} "
            f"{result.split}/{result.mode}"
        )


def validate_existing_manifests(plan, out: Path, conflicting_records) -> None:
    """Fail on the first invalid resume artifact before Docker work continues."""
    selected = plan["selection"]["instance_ids"]
    for position, instance_id in enumerate(selected, 1):
        manifest_path = out / instance_id.replace("/", "_") / "manifest.json"
        if manifest_path.exists():
            print(
                f"[{position}/{len(selected)}] {instance_id}: validating existing manifest",
                flush=True,
            )
            validate_task_manifest(
                plan, instance_id, manifest_path, conflicting_records[instance_id]
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    if plan.get("plan_sha256") != plan_hash(plan):
        raise SystemExit("frozen plan self-hash mismatch")
    if plan.get("parameters", {}).get("grader_environment") != GRADER_ENVIRONMENT:
        raise SystemExit("frozen plan grader environment mismatch")
    declared = (ROOT / plan["environment_validation"]["index_path"]).resolve()
    out = args.out.resolve()
    if declared != out / "index.json":
        raise SystemExit("--out does not match the frozen validation index location")
    pairs, conflicting_records = load_selected_pairs(plan)
    if declared.is_file():
        result = validate_environment_index_for_records(plan, ROOT, conflicting_records)
        print(json.dumps({"status": "already validated", **result}, indent=2))
        return 0

    validate_existing_manifests(plan, out, conflicting_records)
    docker_preflight(os.environ)
    out.mkdir(parents=True, exist_ok=True)
    entries = {}
    pulled_images: set[str] = set()
    selected = plan["selection"]["instance_ids"]
    for position, instance_id in enumerate(selected, 1):
        prefix = f"[{position}/{len(selected)}] {instance_id}"
        task_dir = out / instance_id.replace("/", "_")
        manifest_path = task_dir / "manifest.json"
        original, conflicting = pairs[instance_id]
        if manifest_path.exists():
            print(f"{prefix}: reusing validated manifest", flush=True)
        else:
            print(f"{prefix}: pulling exact image", flush=True)
            pull_image_once(swebench_spec(original)[0], pulled_images, os.environ)
            results = []
            for split, record in (("original", original), ("conflicting", conflicting)):
                for mode in ("nochange", "oracle"):
                    print(f"{prefix}: running {split}/{mode}", flush=True)
                    result = run_trial(
                        record, split=split, mode=mode, out_dir=task_dir,
                        environ=os.environ, memory=plan["parameters"]["memory"],
                        timeout_seconds=plan["parameters"]["scorer_timeout_seconds"],
                    )
                    require_resolved_targets(instance_id, result)
                    results.append(result)
            validate_expected_matrix(results)
            value = trial_manifest(
                plan["dataset"]["revision"], instance_id, original, conflicting, results
            )
            with manifest_path.open("x") as handle:
                json.dump(value, handle, indent=2, sort_keys=True)
                handle.write("\n")
            print(f"{prefix}: validation passed", flush=True)
        entries[instance_id] = {
            "path": str(manifest_path.relative_to(ROOT)), "sha256": sha(manifest_path)
        }
    index = {"schema_version": 1, "status": "validated",
             "plan_sha256": plan["plan_sha256"], "dataset": plan["dataset"],
             "manifests": entries}
    with declared.open("x") as handle:
        json.dump(index, handle, indent=2, sort_keys=True)
        handle.write("\n")
    result = validate_environment_index_for_records(plan, ROOT, conflicting_records)
    print(json.dumps({"status": "validated", **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
