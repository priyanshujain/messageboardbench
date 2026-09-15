"""Screen the frozen v3 candidate pool and derive its paid execution plan."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from messageboardbench.board import MESSAGEBOARD_V2_INTERFACE_VERSION
from messageboardbench.swe_board import (
    NO_STOP_PROMPT_POLICY,
    build_population_plan,
    canonical_hash,
    load_records,
    plan_hash,
    validate_population_plan,
)
from messageboardbench.swe_candidate_pool import (
    EXPECTED_CELLS,
    candidate_order,
    decision_path,
    file_sha256,
    make_decision,
    make_ledger,
    object_sha256,
    rejection_reason,
    result_dicts,
    validate_candidate_pool,
    validate_decision,
)
from messageboardbench.swe_prerequisites import (
    validate_environment_index_for_records,
    validate_task_manifest,
)
from messageboardbench.swe_validation import (
    ValidationError,
    docker_preflight,
    manifest as trial_manifest,
    run_trial,
    swebench_spec,
    validate_expected_matrix,
    validate_pair,
)
ROOT = Path(__file__).resolve().parents[1]


def pull_image_once(image: str, pulled: set[str], environ, run=subprocess.run) -> None:
    if image in pulled:
        return
    result = run(["docker", "pull", image], env=dict(environ), text=True,
                 capture_output=True)
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise ValidationError(f"image pull failed for {image}: {detail}")
    pulled.add(image)


def require_resolved_targets(instance_id: str, result) -> None:
    statuses = result.target_statuses
    if not statuses or any(status in {"MISSING", "ERROR"} for status in statuses.values()):
        raise ValidationError(
            f"validation contains missing/error targets: {instance_id} "
            f"{result.split}/{result.mode}"
        )


def cleanup_candidate_image(
    instance_id: str, image: str, cleanup_path: Path, pulled: set[str], environ,
    run=subprocess.run,
) -> dict:
    """Remove a non-selected image and persist hash-bound lifecycle evidence."""
    if cleanup_path.exists():
        cleanup = json.loads(cleanup_path.read_text())
        if (cleanup.get("instance_id") != instance_id
                or cleanup.get("image") != image
                or cleanup.get("complete") is not True
                or cleanup.get("sha256") != object_sha256(cleanup)):
            raise ValidationError(f"existing image cleanup evidence is invalid: {instance_id}")
        pulled.discard(image)
        return {"path": relative(cleanup_path), "file_sha256": file_sha256(cleanup_path),
                "sha256": cleanup["sha256"]}
    inspected = run(
        ["docker", "image", "inspect", image, "--format", "{{json .}}"],
        env=dict(environ), text=True, capture_output=True,
    )
    inspect_output = (inspected.stdout or "") + (inspected.stderr or "")
    absent = inspected.returncode != 0 and "No such image" in inspect_output
    removed = None
    if inspected.returncode == 0:
        removed = run(
            ["docker", "image", "rm", image], env=dict(environ), text=True,
            capture_output=True,
        )
    complete = absent or (removed is not None and removed.returncode == 0)
    cleanup = {
        "schema_version": 1, "instance_id": instance_id, "image": image,
        "inspect_returncode": inspected.returncode, "inspect_output": inspect_output,
        "already_absent": absent,
        "remove_returncode": removed.returncode if removed is not None else None,
        "remove_output": (
            ((removed.stdout or "") + (removed.stderr or "")) if removed is not None else ""
        ),
        "complete": complete,
    }
    cleanup["sha256"] = object_sha256(cleanup)
    write_new(cleanup_path, cleanup)
    pulled.discard(image)
    if not complete:
        raise ValidationError(f"screening image cleanup failed: {instance_id}")
    return {"path": relative(cleanup_path), "file_sha256": file_sha256(cleanup_path),
            "sha256": cleanup["sha256"]}


def write_new(path: Path, value: dict) -> None:
    """Crash-atomically install JSON without ever replacing an existing artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.tmp-"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve()))


def plan_like(pool: dict, population: dict) -> dict:
    return {"dataset": pool["dataset"], "records_sha256": population["records_sha256"]}


def load_screen_records(pool: dict, population: dict):
    revision = pool["dataset"]["revision"]
    originals = load_records(revision, "original")
    conflicting = load_records(revision, "conflicting")
    original_hashes = {instance_id: canonical_hash(record)
                       for instance_id, record in originals.items()}
    if (canonical_hash(original_hashes) != pool["original_records_sha256_sha256"]
            or set(conflicting) != set(population["records_sha256"])
            or any(canonical_hash(record) != population["records_sha256"][instance_id]
                   for instance_id, record in conflicting.items())):
        raise ValidationError("loaded candidate records differ from the frozen population")
    order = candidate_order(pool["priority_instance_ids"], conflicting, pool["seed"])
    for instance_id in order:
        if instance_id not in originals:
            raise ValidationError(f"candidate missing from original split: {instance_id}")
        validate_pair(originals[instance_id], conflicting[instance_id])
    return order, originals, conflicting


def existing_decisions(pool, population, order, screen_root, conflicting):
    decisions = []
    missing_seen = False
    for index, instance_id in enumerate(order):
        path = decision_path(screen_root, index, instance_id)
        if not path.exists():
            missing_seen = True
            continue
        if missing_seen:
            raise ValueError("screening decisions are not a contiguous candidate-order prefix")
        value = json.loads(path.read_text())
        validate_decision(
            value, pool=pool, index=index, instance_id=instance_id, root=ROOT,
            record=conflicting[instance_id], plan_like=plan_like(pool, population),
        )
        decisions.append(value)
    return decisions


def next_attempt_dir(candidate_dir: Path) -> Path:
    number = 1
    while (candidate_dir / f"attempt-{number:03d}").exists():
        number += 1
    path = candidate_dir / f"attempt-{number:03d}"
    path.mkdir(parents=True)
    return path


def decide_candidate(
    *, pool, population, index, instance_id, original, conflicting,
    screen_root: Path, pulled_images: set[str], environ,
) -> dict:
    candidate_dir = decision_path(screen_root, index, instance_id).parent
    legacy = screen_root / instance_id.replace("/", "_") / "manifest.json"
    base = {
        "pool_sha256": pool["sha256"], "candidate_index": index,
        "instance_id": instance_id,
    }
    if legacy.exists():
        manifest = json.loads(legacy.read_text())
        evidence = {"directory": relative(legacy.parent),
                    "results": manifest.get("results", [])}
        try:
            validate_task_manifest(
                plan_like(pool, population), instance_id, legacy, conflicting
            )
        except (ValueError, OSError, json.JSONDecodeError):
            reason = rejection_reason(evidence["results"], imported_pre_pool=True)
            cleanup = cleanup_candidate_image(
                instance_id, str(manifest.get("image") or swebench_spec(original)[0]),
                legacy.parent / "screen-image-cleanup.json", pulled_images, environ,
            )
            return make_decision(
                **base, status="rejected", reason=reason, evidence=evidence,
                pre_pool_observation=True, image_cleanup=cleanup,
            )
        return make_decision(
            **base, status="passed", evidence=evidence,
            manifest={"path": relative(legacy), "sha256": file_sha256(legacy)},
        )

    attempt = next_attempt_dir(candidate_dir)
    results = []
    reason = None
    print(f"[{index + 1}/{pool['candidate_count']}] {instance_id}: screening", flush=True)
    image = swebench_spec(original)[0]
    try:
        pull_image_once(image, pulled_images, environ)
        expected = {(split, mode): outcome for split, mode, outcome in EXPECTED_CELLS}
        for split, record in (("original", original), ("conflicting", conflicting)):
            for mode in ("nochange", "oracle"):
                print(f"  {split}/{mode}", flush=True)
                result = run_trial(
                    record, split=split, mode=mode, out_dir=attempt,
                    environ=environ, memory=pool["parameters"]["memory"],
                    timeout_seconds=pool["parameters"]["scorer_timeout_seconds"],
                )
                results.append(result)
                try:
                    require_resolved_targets(instance_id, result)
                except ValidationError:
                    reason = rejection_reason(result_dicts(results))
                    break
                if (expected[(split, mode)] is False
                        and "FAILED" not in result.target_statuses.values()):
                    reason = rejection_reason(result_dicts(results))
                    break
            if reason is not None:
                break
    except BaseException as primary:
        try:
            cleanup_candidate_image(
                instance_id, image, attempt / "image-cleanup.json", pulled_images, environ,
            )
        except Exception as cleanup_error:
            primary.add_note(f"image cleanup also failed: {cleanup_error}")
        raise
    if reason is None:
        try:
            validate_expected_matrix(results)
        except ValidationError as matrix_error:
            try:
                reason = rejection_reason(result_dicts(results))
            except ValueError as ground_error:
                try:
                    cleanup_candidate_image(
                        instance_id, image, attempt / "image-cleanup.json",
                        pulled_images, environ,
                    )
                except Exception as cleanup_error:
                    matrix_error.add_note(f"image cleanup also failed: {cleanup_error}")
                matrix_error.add_note(f"not a frozen rejection ground: {ground_error}")
                raise matrix_error
    evidence = {"directory": relative(attempt), "results": result_dicts(results)}
    if reason is not None:
        cleanup = cleanup_candidate_image(
            instance_id, image, attempt / "image-cleanup.json", pulled_images, environ,
        )
        return make_decision(
            **base, status="rejected", reason=reason, evidence=evidence,
            image_cleanup=cleanup,
        )
    manifest_path = attempt / "manifest.json"
    manifest = trial_manifest(
        pool["dataset"]["revision"], instance_id, original, conflicting, results
    )
    write_new(manifest_path, manifest)
    validate_task_manifest(
        plan_like(pool, population), instance_id, manifest_path, conflicting
    )
    return make_decision(
        **base, status="passed", evidence=evidence,
        manifest={"path": relative(manifest_path), "sha256": file_sha256(manifest_path)},
    )


def derive_plan(template, pool, pool_path, ledger, ledger_path, records, screen_root):
    selected = ledger["selected_instance_ids"]
    plan = build_population_plan(
        records, revision=template["dataset"]["revision"], model=template["model"],
        upstream_git_commit=template["upstream_git_commit"], teams=1, cohorts=2,
        seed=template["seed"], selected_instance_ids=selected,
        tool_interface=MESSAGEBOARD_V2_INTERFACE_VERSION,
        prompt_policy=NO_STOP_PROMPT_POLICY,
    )
    plan["selection"] = {
        "kind": "screened_candidate_pool",
        "instance_ids": selected,
        "source_population_count": pool["candidate_count"],
        "candidate_pool": {"path": relative(pool_path), "file_sha256": file_sha256(pool_path),
                           "sha256": pool["sha256"]},
        "screening_ledger": {"path": relative(ledger_path),
                             "file_sha256": file_sha256(ledger_path),
                             "sha256": ledger["sha256"]},
        "selected_manifest_sha256": ledger["selected_manifests"],
    }
    plan["environment_validation"] = {
        "required_before_execution": True,
        "index_path": relative(screen_root / "index.json"),
    }
    plan["plan_sha256"] = plan_hash(plan)
    return plan


def make_selected_index(plan, decisions, screen_root):
    selected = set(plan["selection"]["instance_ids"])
    entries = {
        row["instance_id"]: row["manifest"] for row in decisions
        if row["instance_id"] in selected and row["status"] == "passed"
    }
    return {"schema_version": 1, "status": "validated",
            "plan_sha256": plan["plan_sha256"], "dataset": plan["dataset"],
            "manifests": entries}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--screen-root", type=Path, required=True)
    parser.add_argument("--derived-plan", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    pool_path = args.pool.resolve()
    pool = json.loads(pool_path.read_text())
    order, population = validate_candidate_pool(pool, ROOT)
    template_bytes = args.template.read_bytes()
    template = json.loads(template_bytes)
    if (plan_hash(template) != template.get("plan_sha256")
            or file_sha256(args.template) != pool.get("template_plan", {}).get("file_sha256")
            or template.get("plan_sha256") != pool.get("template_plan", {}).get("plan_sha256")):
        raise SystemExit("candidate pool template-plan binding mismatch")
    if (template.get("dataset") != pool.get("dataset")
            or template.get("seed") != pool.get("seed")
            or template.get("model") != "openrouter/z-ai/glm-5.3-flash"
            or template.get("custom_prompt") != ""
            or template.get("prompt_policy") != NO_STOP_PROMPT_POLICY
            or template.get("tool_interface") != MESSAGEBOARD_V2_INTERFACE_VERSION
            or template.get("organizer_feedback_interface") != "organizer-feedback-v1"
            or template.get("upstream_system_prompt", {}).get("prompt_suffix")
            != "**DO NOT MODIFY THE TESTS.**"
            or pool.get("parameters") != {
                "memory": template.get("parameters", {}).get("memory"),
                "scorer_timeout_seconds": template.get("parameters", {}).get(
                    "scorer_timeout_seconds"
                ),
            }):
        raise SystemExit("candidate pool differs from the frozen v3 treatment template")
    if args.validate_only:
        print(json.dumps({"status": "ready-to-screen", "pool_sha256": pool["sha256"],
                          "candidate_count": len(order)}, indent=2))
        return 0

    screen_root = args.screen_root.resolve()
    derived_path = args.derived_plan.resolve()
    if not screen_root.is_relative_to(ROOT) or not derived_path.is_relative_to(ROOT):
        raise SystemExit("screen and derived-plan paths must remain under the repository")
    order, originals, conflicting = load_screen_records(pool, population)
    decisions = existing_decisions(pool, population, order, screen_root, conflicting)
    if len([row for row in decisions if row["status"] == "passed"]) < pool["target_pass_count"]:
        docker_preflight(os.environ)
    pulled_images: set[str] = set()
    for index in range(len(decisions), len(order)):
        if len([row for row in decisions if row["status"] == "passed"]) >= pool["target_pass_count"]:
            break
        instance_id = order[index]
        decision = decide_candidate(
            pool=pool, population=population, index=index, instance_id=instance_id,
            original=originals[instance_id], conflicting=conflicting[instance_id],
            screen_root=screen_root, pulled_images=pulled_images, environ=os.environ,
        )
        path = decision_path(screen_root, index, instance_id)
        write_new(path, decision)
        validate_decision(
            decision, pool=pool, index=index, instance_id=instance_id, root=ROOT,
            record=conflicting[instance_id], plan_like=plan_like(pool, population),
        )
        decisions.append(decision)
        print(f"  decision: {decision['status']}", flush=True)
    ledger = make_ledger(pool, decisions)
    ledger_path = screen_root / "ledger.json"
    if ledger_path.exists():
        if json.loads(ledger_path.read_text()) != ledger:
            raise ValueError("existing screening ledger differs from deterministic reconstruction")
    else:
        write_new(ledger_path, ledger)
    plan = derive_plan(
        template, pool, pool_path, ledger, ledger_path, conflicting, screen_root
    )
    if derived_path.exists():
        if json.loads(derived_path.read_text()) != plan:
            raise ValueError("existing derived plan differs from deterministic reconstruction")
    else:
        write_new(derived_path, plan)
    validate_population_plan(plan, conflicting)
    index = make_selected_index(plan, decisions, screen_root)
    index_path = screen_root / "index.json"
    if index_path.exists():
        if json.loads(index_path.read_text()) != index:
            raise ValueError("existing selected validation index differs")
    else:
        write_new(index_path, index)
    validate_environment_index_for_records(plan, ROOT, conflicting)
    print(json.dumps({"status": "ready-for-paid-execution", "plan": relative(derived_path),
                      "plan_sha256": plan["plan_sha256"],
                      "selected": ledger["selected_instance_ids"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
