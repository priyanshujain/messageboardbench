"""Build or validate the no-model SWE readiness index for a frozen pilot."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from messageboardbench.swe_board import load_records, plan_hash
from messageboardbench.swe_prerequisites import validate_environment_index_for_records
from messageboardbench.swe_validation import (
    ValidationError,
    docker_preflight,
    load_pair,
    manifest as trial_manifest,
    run_trial,
    swebench_spec,
    validate_expected_matrix,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    if plan.get("plan_sha256") != plan_hash(plan):
        raise SystemExit("frozen plan self-hash mismatch")
    declared = (ROOT / plan["environment_validation"]["index_path"]).resolve()
    out = args.out.resolve()
    if declared != out / "index.json":
        raise SystemExit("--out does not match the frozen validation index location")
    if declared.is_file():
        records = load_records(plan["dataset"]["revision"], "conflicting")
        result = validate_environment_index_for_records(plan, ROOT, records)
        print(json.dumps({"status": "already validated", **result}, indent=2))
        return 0

    docker_preflight(os.environ)
    out.mkdir(parents=True, exist_ok=True)
    entries = {}
    pulled_images: set[str] = set()
    for instance_id in plan["selection"]["instance_ids"]:
        task_dir = out / instance_id.replace("/", "_")
        manifest_path = task_dir / "manifest.json"
        if not manifest_path.exists():
            original, conflicting = load_pair(plan["dataset"]["revision"], instance_id)
            pull_image_once(swebench_spec(original)[0], pulled_images, os.environ)
            results = [
                run_trial(record, split=split, mode=mode, out_dir=task_dir,
                          environ=os.environ,
                          memory=plan["parameters"]["memory"],
                          timeout_seconds=plan["parameters"]["scorer_timeout_seconds"])
                for split, record in (("original", original), ("conflicting", conflicting))
                for mode in ("nochange", "oracle")
            ]
            validate_expected_matrix(results)
            value = trial_manifest(
                plan["dataset"]["revision"], instance_id, original, conflicting, results
            )
            with manifest_path.open("x") as handle:
                json.dump(value, handle, indent=2, sort_keys=True)
                handle.write("\n")
        entries[instance_id] = {
            "path": str(manifest_path.relative_to(ROOT)), "sha256": sha(manifest_path)
        }
    index = {"schema_version": 1, "status": "validated",
             "plan_sha256": plan["plan_sha256"], "dataset": plan["dataset"],
             "manifests": entries}
    with declared.open("x") as handle:
        json.dump(index, handle, indent=2, sort_keys=True)
        handle.write("\n")
    records = load_records(plan["dataset"]["revision"], "conflicting")
    result = validate_environment_index_for_records(plan, ROOT, records)
    print(json.dumps({"status": "validated", **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
