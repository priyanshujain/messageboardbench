"""Frozen candidate-pool and append-only screening provenance for SWE pilot v3."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from messageboardbench.swe_board import canonical_hash, plan_hash
from messageboardbench.swe_prerequisites import validate_task_manifest


POOL_SCHEMA = 1
LEDGER_SCHEMA = 1
RANKING_NAMESPACE = "swe-pilot-v3-candidate-pool-v1"
PRE_POOL_OBSERVATION = {
    "instance_id": "django__django-15315",
    "disclosure": (
        "A pre-pool validation attempt observed all conflicting targets as MISSING; "
        "its preserved manifest is imported and revalidated by the frozen rule."
    ),
}
EXPECTED_CELLS = (
    ("original", "nochange", False),
    ("original", "oracle", True),
    ("conflicting", "nochange", False),
    ("conflicting", "oracle", False),
)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def object_sha256(value: Mapping[str, Any]) -> str:
    unhashed = dict(value)
    unhashed.pop("sha256", None)
    return canonical_hash(unhashed)


def candidate_order(priority: Sequence[str], population: Sequence[str], seed: int) -> list[str]:
    """Put v2 tasks first, then deterministically rank every unused task."""
    priority = list(priority)
    population = list(population)
    if len(priority) != len(set(priority)) or not set(priority) <= set(population):
        raise ValueError("candidate-pool priority IDs are invalid")
    unused = set(population) - set(priority)
    ranked = sorted(
        unused,
        key=lambda instance_id: hashlib.sha256(
            f"{RANKING_NAMESPACE}:{seed}:{instance_id}".encode()
        ).digest(),
    )
    return [*priority, *ranked]


def _bound_json(root: Path, reference: Mapping[str, Any], label: str) -> dict[str, Any]:
    value = reference.get("path")
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError(f"{label} path must be repository-relative")
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()) or file_sha256(path) != reference.get("file_sha256"):
        raise ValueError(f"{label} file hash mismatch")
    document = json.loads(path.read_text())
    if (document.get("plan_sha256") != reference.get("plan_sha256")
            or plan_hash(document) != document.get("plan_sha256")):
        raise ValueError(f"{label} plan hash mismatch")
    return document


def validate_candidate_pool(pool: Mapping[str, Any], root: Path) -> tuple[list[str], dict[str, Any]]:
    """Validate the pre-screen pool and reconstruct its exact committed order."""
    if (pool.get("schema_version") != POOL_SCHEMA or pool.get("status") != "frozen"
            or pool.get("purpose") != "swe-population-pilot-v3-candidate-pool"
            or pool.get("target_pass_count") != 10
            or pool.get("ranking_namespace") != RANKING_NAMESPACE
            or pool.get("pre_pool_observation") != PRE_POOL_OBSERVATION
            or pool.get("sha256") != object_sha256(pool)):
        raise ValueError("candidate pool identity or self-hash mismatch")
    population = _bound_json(root, pool.get("population_source", {}), "population source")
    v2 = _bound_json(root, pool.get("priority_source", {}), "priority source")
    if (population.get("purpose") != "population-propensity-control-vs-board-swe"
            or v2.get("purpose") != "population-propensity-control-vs-board-swe-pilot-v2"
            or population.get("instance_count") != len(population.get("records_sha256", {}))
            or population.get("dataset") != pool.get("dataset")
            or v2.get("dataset") != pool.get("dataset")
            or canonical_hash(population.get("records_sha256", {}))
            != pool.get("records_sha256_sha256")
            or not isinstance(pool.get("original_records_sha256_sha256"), str)):
        raise ValueError("candidate pool dataset or record hashes mismatch")
    priority = v2.get("selection", {}).get("instance_ids")
    if priority != pool.get("priority_instance_ids"):
        raise ValueError("candidate pool does not exactly prioritize the v2 selection")
    order = candidate_order(priority, population["records_sha256"], pool.get("seed"))
    if (len(order) != pool.get("candidate_count")
            or len(order) != population.get("instance_count")
            or canonical_hash(order) != pool.get("candidate_order_sha256")):
        raise ValueError("candidate order does not match its frozen commitment")
    return order, population


def decision_path(screen_root: Path, index: int, instance_id: str) -> Path:
    return screen_root / "decisions" / f"{index:03d}-{instance_id}" / "decision.json"


def validate_decision(
    decision: Mapping[str, Any], *, pool: Mapping[str, Any], index: int,
    instance_id: str, root: Path, record: Mapping[str, Any], plan_like: Mapping[str, Any],
) -> None:
    """Validate an immutable pass/reject receipt and every referenced byte."""
    if (decision.get("schema_version") != 1
            or decision.get("pool_sha256") != pool.get("sha256")
            or decision.get("candidate_index") != index
            or decision.get("instance_id") != instance_id
            or decision.get("status") not in {"passed", "rejected"}
            or decision.get("sha256") != object_sha256(decision)):
        raise ValueError(f"screening decision identity mismatch: {instance_id}")
    evidence = decision.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError(f"screening decision lacks evidence: {instance_id}")
    evidence_dir = (root / evidence.get("directory", "")).resolve()
    if not evidence_dir.is_relative_to(root.resolve()):
        raise ValueError(f"screening evidence path escapes repository: {instance_id}")
    results = evidence.get("results")
    if not isinstance(results, list):
        raise ValueError(f"screening decision results missing: {instance_id}")
    for row in results:
        output = evidence_dir / str(row.get("output_file", ""))
        if not output.is_file() or file_sha256(output) != row.get("output_sha256"):
            raise ValueError(f"screening output hash mismatch: {instance_id}")
    if decision["status"] == "passed":
        manifest_ref = decision.get("manifest")
        if not isinstance(manifest_ref, dict):
            raise ValueError(f"passed decision lacks manifest: {instance_id}")
        manifest_path = (root / manifest_ref.get("path", "")).resolve()
        if (not manifest_path.is_relative_to(root.resolve())
                or file_sha256(manifest_path) != manifest_ref.get("sha256")):
            raise ValueError(f"passed manifest hash mismatch: {instance_id}")
        validate_task_manifest(plan_like, instance_id, manifest_path, record)
        manifest = json.loads(manifest_path.read_text())
        if results != manifest.get("results"):
            raise ValueError(f"passed decision evidence differs from manifest: {instance_id}")
    else:
        imported = decision.get("pre_pool_observation") is True
        if imported and instance_id != PRE_POOL_OBSERVATION["instance_id"]:
            raise ValueError(f"invalid pre-pool observation receipt: {instance_id}")
        expected_reason = rejection_reason(results, imported_pre_pool=imported)
        if decision.get("reason") != expected_reason:
            raise ValueError(f"rejected decision ground mismatch: {instance_id}")
        cleanup_ref = decision.get("image_cleanup")
        if not isinstance(cleanup_ref, dict):
            raise ValueError(f"rejected decision lacks image cleanup: {instance_id}")
        cleanup_path = (root / cleanup_ref.get("path", "")).resolve()
        if (not cleanup_path.is_relative_to(root.resolve())
                or not cleanup_path.is_file()
                or file_sha256(cleanup_path) != cleanup_ref.get("file_sha256")):
            raise ValueError(f"image cleanup evidence hash mismatch: {instance_id}")
        cleanup = json.loads(cleanup_path.read_text())
        evidence_images = {row.get("image") for row in results}
        if (cleanup.get("schema_version") != 1
                or cleanup.get("instance_id") != instance_id
                or evidence_images != {cleanup.get("image")}
                or cleanup.get("complete") is not True
                or cleanup.get("sha256") != object_sha256(cleanup)
                or cleanup.get("sha256") != cleanup_ref.get("sha256")):
            raise ValueError(f"image cleanup evidence is incomplete: {instance_id}")


def rejection_reason(
    results: Sequence[Mapping[str, Any]], *, imported_pre_pool: bool = False
) -> str:
    """Return the sole evidence-derived rejection reason, or reject exclusion."""
    if not results or len(results) > len(EXPECTED_CELLS):
        raise ValueError("rejection evidence must be a nonempty matrix prefix")
    observed_cells = [(row.get("split"), row.get("mode")) for row in results]
    expected_prefix = [(split, mode) for split, mode, _ in EXPECTED_CELLS[:len(results)]]
    if observed_cells != expected_prefix:
        raise ValueError("rejection evidence is not an ordered matrix prefix")
    identities = {
        (row.get("image"), row.get("image_id"), tuple(row.get("repo_digests") or []),
         tuple(row.get("test_command") or []))
        for row in results
    }
    if len(identities) != 1:
        raise ValueError("rejection evidence used divergent image or test identities")
    bad = [
        position for position, row in enumerate(results)
        if not isinstance(row.get("target_statuses"), dict)
        or not row["target_statuses"]
        or any(status in {"MISSING", "ERROR"}
               for status in row["target_statuses"].values())
    ]
    if bad:
        first = bad[0]
        if imported_pre_pool:
            if len(results) != len(EXPECTED_CELLS):
                raise ValueError("imported pre-pool rejection must preserve its full matrix")
        elif first != len(results) - 1:
            raise ValueError("screening continued after the first missing/error target")
        split, mode = observed_cells[first]
        return f"target-status rejection: {split}/{mode} contains MISSING/ERROR"
    no_failed = [
        position for position, (row, (_, _, expected)) in enumerate(
            zip(results, EXPECTED_CELLS)
        )
        if expected is False and "FAILED" not in row["target_statuses"].values()
    ]
    if no_failed:
        first = no_failed[0]
        if imported_pre_pool:
            if len(results) != len(EXPECTED_CELLS):
                raise ValueError("imported pre-pool rejection must preserve its full matrix")
        elif first != len(results) - 1:
            raise ValueError("screening continued after an unresolved cell without FAILED")
        split, mode = observed_cells[first]
        return f"target-status rejection: {split}/{mode} has no FAILED target"
    if len(results) != len(EXPECTED_CELLS):
        raise ValueError("unfinished eligible prefix is not a rejection ground")
    mismatches = [
        f"{split}/{mode}={row.get('resolved')!r}"
        for row, (split, mode, expected) in zip(results, EXPECTED_CELLS)
        if row.get("resolved") is not expected
    ]
    if not mismatches:
        raise ValueError("eligible matrix cannot receive a rejection receipt")
    return "outcome-matrix rejection: " + ", ".join(mismatches)


def make_decision(**fields: Any) -> dict[str, Any]:
    value = {"schema_version": 1, **fields}
    value["sha256"] = object_sha256(value)
    return value


def make_ledger(pool: Mapping[str, Any], decisions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    passed = [row for row in decisions if row["status"] == "passed"]
    target = pool["target_pass_count"]
    if len(passed) < target:
        raise ValueError("cannot finalize screening before enough candidates pass")
    selected = passed[:target]
    last_index = selected[-1]["candidate_index"]
    included = [row for row in decisions if row["candidate_index"] <= last_index]
    value = {
        "schema_version": LEDGER_SCHEMA,
        "status": "complete",
        "pool_sha256": pool["sha256"],
        "target_pass_count": target,
        "decisions": [
            {"candidate_index": row["candidate_index"], "instance_id": row["instance_id"],
             "status": row["status"], "decision_sha256": row["sha256"]}
            for row in included
        ],
        "selected_instance_ids": [row["instance_id"] for row in selected],
        "selected_manifests": {
            row["instance_id"]: row["manifest"]["sha256"] for row in selected
        },
    }
    value["sha256"] = object_sha256(value)
    return value


def result_dicts(results: Sequence[Any]) -> list[dict[str, Any]]:
    return [asdict(row) for row in results]


def validate_screened_execution_plan(
    plan: Mapping[str, Any], root: Path, records: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Replay the pool, receipts, selection, and manifest bindings for paid use."""
    selection = plan.get("selection", {})
    if selection.get("kind") != "screened_candidate_pool":
        raise ValueError("execution plan does not use screened candidate-pool selection")
    pool_ref = selection["candidate_pool"]
    ledger_ref = selection["screening_ledger"]
    pool_path = (root / pool_ref["path"]).resolve()
    ledger_path = (root / ledger_ref["path"]).resolve()
    if (not pool_path.is_relative_to(root.resolve())
            or not ledger_path.is_relative_to(root.resolve())
            or file_sha256(pool_path) != pool_ref["file_sha256"]
            or file_sha256(ledger_path) != ledger_ref["file_sha256"]):
        raise ValueError("screened selection file binding mismatch")
    pool = json.loads(pool_path.read_text())
    order, population = validate_candidate_pool(pool, root)
    ledger = json.loads(ledger_path.read_text())
    if (ledger.get("schema_version") != LEDGER_SCHEMA
            or ledger.get("status") != "complete"
            or ledger.get("pool_sha256") != pool["sha256"]
            or ledger.get("sha256") != object_sha256(ledger)
            or ledger.get("sha256") != ledger_ref["sha256"]):
        raise ValueError("screening ledger identity or self-hash mismatch")
    plan_like = {"dataset": pool["dataset"], "records_sha256": population["records_sha256"]}
    decisions = []
    for expected_index, receipt in enumerate(ledger.get("decisions", [])):
        instance_id = order[expected_index]
        if (receipt.get("candidate_index") != expected_index
                or receipt.get("instance_id") != instance_id):
            raise ValueError("screening ledger is not a contiguous candidate prefix")
        path = decision_path(ledger_path.parent, expected_index, instance_id)
        decision = json.loads(path.read_text())
        if decision.get("sha256") != receipt.get("decision_sha256"):
            raise ValueError(f"screening receipt hash mismatch: {instance_id}")
        record = records.get(instance_id)
        if record is None:
            raise ValueError(f"selected dataset record missing: {instance_id}")
        validate_decision(
            decision, pool=pool, index=expected_index, instance_id=instance_id,
            root=root, record=record, plan_like=plan_like,
        )
        decisions.append(decision)
    replayed = make_ledger(pool, decisions)
    if replayed != ledger:
        raise ValueError("screening ledger differs from deterministic replay")
    if (ledger["selected_instance_ids"] != selection.get("instance_ids")
            or ledger["selected_manifests"] != selection.get("selected_manifest_sha256")):
        raise ValueError("execution selection differs from screening ledger")
    return {"pool": pool, "ledger": ledger, "decisions": decisions}
