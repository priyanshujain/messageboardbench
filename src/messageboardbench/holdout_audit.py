"""Reproducible, model-free audit records for held-out benchmark tasks.

Candidate generation performs mechanical checks only. A separate freeze step
requires an explicit semantic review record before emitting the ``status: ready``
schema consumed by the confirmatory board runner. Reviews identify whether they
were performed by a human or by two independent internal Codex research assistants.
"""

from __future__ import annotations

import ast
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Callable, Iterable

from messageboardbench.prompt_calibration import DEFAULT_PARTITIONS


DATASET_PATH = "fjzzq2002/impossible_livecodebench"
COMMUNICATION_HOLDOUT = DEFAULT_PARTITIONS.communication_holdout
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVIEWER_TYPES = {"human", "internal_codex_dual_review"}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_revision(revision: str) -> str:
    revision = revision.lower()
    if not COMMIT_RE.fullmatch(revision):
        raise ValueError("dataset revision must be a full 40-character hexadecimal commit")
    return revision


def resolve_revision(path: str = DATASET_PATH) -> str:
    """Resolve the current Hub ref to a commit; callers record the returned commit."""
    from huggingface_hub import HfApi

    revision = HfApi().dataset_info(path).sha
    if revision is None:
        raise ValueError(f"Hugging Face did not return a commit for {path}")
    return validate_revision(revision)


def load_samples(revision: str) -> dict[str, dict[str, object]]:
    """Load both evaluator variants using the same adapter as the board runner."""
    from inspect_ai.dataset import hf_dataset
    from impossiblebench.livecodebench_tasks import (
        INSTRUCTION,
        INSTRUCTION_SUFFIX_TOOLS,
        record_to_sample,
    )

    revision = validate_revision(revision)
    instruction = INSTRUCTION + " **DO NOT MODIFY THE TESTS.**" + INSTRUCTION_SUFFIX_TOOLS
    return {
        split: {
            str(sample.id): sample
            for sample in hf_dataset(
                path=DATASET_PATH,
                split=split,
                revision=revision,
                sample_fields=record_to_sample(instruction_prompt=instruction),
            )
        }
        for split in ("original", "conflicting")
    }


def _candidate_call(node: ast.AST) -> ast.Call | None:
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "candidate"
    ):
        return node
    return None


def _asserted_outcome(compare: ast.Compare) -> tuple[str, str] | None:
    """Return a normalized outcome predicate, rejecting unsupported comparisons."""
    if len(compare.ops) != 1 or len(compare.comparators) != 1:
        return None
    operator = compare.ops[0]
    expected = compare.comparators[0]
    if isinstance(operator, ast.Eq):
        return (
            "eq:" + ast.dump(expected, include_attributes=False),
            ast.unparse(expected),
        )
    if isinstance(operator, (ast.Is, ast.IsNot)) and isinstance(expected, ast.Constant):
        label = "is" if isinstance(operator, ast.Is) else "is_not"
        rendered = f"is{' not' if label == 'is_not' else ''} {ast.unparse(expected)}"
        return f"{label}:{expected.value!r}", rendered
    return None


def _assertion_rows(source: str) -> list[dict]:
    """Extract simple assertions about a candidate call's returned outcome.

    Supported forms are a direct ``candidate(...) ==/is/is not value`` or a simple
    top-level assignment followed later by the same comparison against that name.
    The deliberately narrow, statement-ordered dataflow is fail-closed: aliases,
    branches, mutations and compound comparisons are not inferred.
    """
    tree = ast.parse(source)
    checks = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "check"
    ]
    if len(checks) != 1:
        return []
    bound_calls: dict[str, ast.Call] = {}
    rows = []
    for node in checks[0].body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            call = _candidate_call(node.value)
            if call is None:
                bound_calls.pop(name, None)
            else:
                bound_calls[name] = call
            continue
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            call = _candidate_call(node.value) if node.value is not None else None
            if call is None:
                bound_calls.pop(node.target.id, None)
            else:
                bound_calls[node.target.id] = call
            continue
        if not isinstance(node, ast.Assert) or not isinstance(node.test, ast.Compare):
            continue
        outcome = _asserted_outcome(node.test)
        if outcome is None:
            continue
        left = node.test.left
        call = _candidate_call(left)
        if call is None and isinstance(left, ast.Name):
            call = bound_calls.get(left.id)
        if call is None:
            continue
        outcome_key, rendered = outcome
        rows.append(
            {
                "call_ast": ast.dump(call, include_attributes=False),
                "call": ast.unparse(call),
                "expected_ast": outcome_key,
                "expected": rendered,
                "line": node.lineno,
            }
        )
    return rows


def _outcomes_incompatible(first: str, second: str) -> bool:
    if first == second:
        return False
    first_kind, first_value = first.split(":", 1)
    second_kind, second_value = second.split(":", 1)
    if first_kind == second_kind == "eq":
        return first_value != second_value
    if {first_kind, second_kind} == {"is", "is_not"}:
        return first_value == second_value
    # Mixed equality/identity predicates are intentionally not inferred.
    return False


def _contradiction_evidence(original_test: str, conflicting_test: str) -> dict:
    original = _assertion_rows(original_test)
    conflicting = _assertion_rows(conflicting_test)
    original_counts = Counter((row["call_ast"], row["expected_ast"]) for row in original)
    remaining = original_counts.copy()
    added = []
    for row in conflicting:
        key = row["call_ast"], row["expected_ast"]
        if remaining[key]:
            remaining[key] -= 1
        else:
            added.append(row)

    contradictions = []
    for new in added:
        prior = [
            old
            for old in original
            if old["call_ast"] == new["call_ast"]
            and _outcomes_incompatible(old["expected_ast"], new["expected_ast"])
        ]
        if prior:
            contradictions.append(
                {
                    "call": new["call"],
                    "conflicting_expected": new["expected"],
                    "conflicting_line": new["line"],
                    "original_expected_values": [row["expected"] for row in prior],
                    "original_lines": [row["line"] for row in prior],
                }
            )
    return {
        "original_assertion_count": len(original),
        "conflicting_assertion_count": len(conflicting),
        "added_assertion_count": len(added),
        "same_call_incompatible_expected_value_count": len(contradictions),
        "same_call_incompatible_expected_values": contradictions,
    }


def _metadata_text(sample: object, field: str, task_id: str, split: str) -> str:
    metadata = getattr(sample, "metadata", None) or {}
    value = metadata.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{split}/{task_id} lacks non-empty metadata.{field}")
    return value


def build_candidate(
    revision: str,
    *,
    task_ids: Iterable[str] = COMMUNICATION_HOLDOUT,
    partition: str = "communication_holdout",
    loader: Callable[[str], dict[str, dict[str, object]]] = load_samples,
) -> dict:
    """Build mechanical evidence without asserting semantic evaluator validity."""
    revision = validate_revision(revision)
    task_ids = tuple(task_ids)
    if not task_ids or len(task_ids) != len(set(task_ids)):
        raise ValueError("task IDs must be a non-empty, duplicate-free sequence")
    allowed_partitions = {
        "communication_holdout": set(DEFAULT_PARTITIONS.communication_holdout),
        "validation": set(DEFAULT_PARTITIONS.validation),
    }
    if partition not in allowed_partitions:
        raise ValueError("audit partition must be communication_holdout or validation")
    outside = sorted(set(task_ids) - allowed_partitions[partition])
    if outside:
        raise ValueError(f"candidate contains IDs outside {partition.replace('_', ' ')}: {outside}")
    datasets = loader(revision)
    rows = []
    for task_id in task_ids:
        try:
            original = datasets["original"][task_id]
            conflicting = datasets["conflicting"][task_id]
        except KeyError as exc:
            raise ValueError(f"pinned dataset is missing required task {task_id}") from exc
        oprompt = _metadata_text(original, "prompt", task_id, "original")
        cprompt = _metadata_text(conflicting, "prompt", task_id, "conflicting")
        otest = _metadata_text(original, "test", task_id, "original")
        ctest = _metadata_text(conflicting, "test", task_id, "conflicting")
        oentry = _metadata_text(original, "entry_point", task_id, "original")
        centry = _metadata_text(conflicting, "entry_point", task_id, "conflicting")
        evidence = _contradiction_evidence(otest, ctest)
        checks = {
            "present_in_both_splits": True,
            "prompt_bytes_identical_across_splits": oprompt == cprompt,
            "entry_point_identical_across_splits": oentry == centry,
            "test_bytes_differ_across_splits": otest != ctest,
            "python_tests_parse": True,
            "exactly_one_added_assertion": evidence["added_assertion_count"] == 1,
            "added_assertion_conflicts_with_original_same_call": (
                evidence["same_call_incompatible_expected_value_count"] == 1
            ),
        }
        for reviewed_split, reviewed_test in (
            (("conflicting", ctest),) if partition == "communication_holdout"
            else (("original", otest), ("conflicting", ctest))
        ):
            rows.append({
                "task_id": task_id,
                "split": reviewed_split,
                "entry_point": oentry,
                "task_prompt_sha256": sha256_text(cprompt if reviewed_split == "conflicting" else oprompt),
                "test_sha256": sha256_text(reviewed_test),
                "original_test_sha256": sha256_text(otest),
                "automated_checks": checks,
                "contradiction_evidence": evidence,
                # Exact bytes are included in the ignored candidate packet so a
                # reviewer can assess semantics, not merely approve hashes.
                "review_material": {
                    "task_prompt": cprompt,
                    "original_test": otest,
                    "conflicting_test": ctest,
                },
                "semantic_review_required": {
                    "task_valid_for_specification": True,
                    "original_evaluator_valid_for_specification": True,
                    "conflicting_evaluator_is_genuinely_contradictory": True,
                },
            })
    all_mechanical_checks_pass = all(
        all(row["automated_checks"].values()) for row in rows
    )
    return {
        "schema_version": 2,
        "kind": "holdout-audit-candidate",
        "status": "needs_semantic_review",
        "dataset": {"path": DATASET_PATH, "revision": revision},
        "partition": partition,
        "requested_pairs": [
            {"task_id": task_id, "split": split}
            for task_id in task_ids
            for split in (("conflicting",) if partition == "communication_holdout"
                          else ("original", "conflicting"))
        ],
        "candidate_pairs": rows,
        "all_mechanical_checks_pass": all_mechanical_checks_pass,
        "limitations": [
            "Mechanical AST checks do not establish that the task specification is coherent.",
            "Mechanical AST checks do not establish that the original expected answers are correct.",
            "No model behavior or outcome was executed or inspected by this workflow.",
        ],
    }


def candidate_review_template(candidate_bytes: bytes) -> dict:
    candidate = json.loads(candidate_bytes)
    if candidate.get("kind") != "holdout-audit-candidate":
        raise ValueError("not a holdout audit candidate")
    if candidate.get("schema_version") != 2 or candidate.get("status") != "needs_semantic_review":
        raise ValueError("candidate must use semantic-review schema_version 2")
    return {
        "schema_version": 2,
        "candidate_sha256": sha256_bytes(candidate_bytes),
        "reviewer_type": "human",
        "reviewer": "REPLACE_WITH_REVIEWER_NAME",
        "reviewers": [],
        "reviewed_at": "REPLACE_WITH_ISO_8601_TIMESTAMP",
        "no_model_outcomes_inspected": True,
        "decisions": [
            {
                "task_id": row["task_id"],
                "split": row["split"],
                "task_validated": False,
                "evaluator_validated": False,
                "notes": "REVIEW_TASK_SPEC_AND_BOTH_EVALUATORS",
            }
            for row in candidate["candidate_pairs"]
        ],
    }


def freeze_reviewed_audit(candidate_bytes: bytes, review: dict) -> dict:
    """Validate explicit review decisions and emit board_pilot's ready schema."""
    candidate = json.loads(candidate_bytes)
    if candidate.get("kind") != "holdout-audit-candidate":
        raise ValueError("not a holdout audit candidate")
    if candidate.get("schema_version") != 2:
        raise ValueError("candidate schema_version must be 2")
    if candidate.get("status") != "needs_semantic_review":
        raise ValueError("candidate has an unexpected status")
    if candidate.get("all_mechanical_checks_pass") is not True:
        raise ValueError("cannot freeze a candidate with failed mechanical checks")
    if review.get("schema_version") != 2:
        raise ValueError("review schema_version must be 2")
    if review.get("candidate_sha256") != sha256_bytes(candidate_bytes):
        raise ValueError("review does not bind to the exact candidate bytes")
    reviewer_type = review.get("reviewer_type")
    if reviewer_type not in REVIEWER_TYPES:
        raise ValueError(f"reviewer_type must be one of {sorted(REVIEWER_TYPES)}")
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip() or reviewer.startswith("REPLACE_"):
        raise ValueError("review must name its reviewer or review group")
    reviewers = review.get("reviewers", [])
    if not isinstance(reviewers, list):
        raise ValueError("reviewers must be a list")
    if reviewer_type == "human":
        if reviewers:
            raise ValueError("human review records one reviewer in the reviewer field")
    else:
        if len(reviewers) != 2:
            raise ValueError("internal_codex_dual_review requires exactly two reviewers")
        names = []
        roles = []
        for item in reviewers:
            if not isinstance(item, dict):
                raise ValueError("dual-review reviewer records must be objects")
            name = item.get("name")
            role = item.get("role")
            path = item.get("evidence_path")
            digest = item.get("evidence_sha256")
            if not isinstance(name, str) or not name.strip() or name.startswith("REPLACE_"):
                raise ValueError("dual review must name both internal reviewers")
            if not isinstance(role, str) or not role.strip():
                raise ValueError("dual review must state each reviewer's role")
            if not isinstance(path, str) or not path.strip():
                raise ValueError("dual review must cite both evidence paths")
            if not SHA256_RE.fullmatch(str(digest)):
                raise ValueError("dual review evidence must include valid SHA-256 hashes")
            names.append(name)
            roles.append(role)
        if len(set(names)) != 2 or len(set(roles)) != 2:
            raise ValueError("dual review requires distinct reviewer identities and roles")
    reviewed_at = review.get("reviewed_at")
    if not isinstance(reviewed_at, str) or reviewed_at.startswith("REPLACE_"):
        raise ValueError("review must include an ISO-8601 reviewed_at timestamp")
    try:
        datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("reviewed_at must be an ISO-8601 timestamp") from exc
    if review.get("no_model_outcomes_inspected") is not True:
        raise ValueError("review must affirm that no model outcomes were inspected")

    decisions = review.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("review decisions must be a list")
    indexed = {(row.get("task_id"), row.get("split")): row for row in decisions}
    expected = {(row["task_id"], row["split"]): row for row in candidate["candidate_pairs"]}
    if len(indexed) != len(decisions) or indexed.keys() != expected.keys():
        raise ValueError("review decisions must match candidate pairs exactly without duplicates")
    approved = []
    for pair, candidate_row in expected.items():
        decision = indexed[pair]
        if decision.get("task_validated") is not True:
            raise ValueError(f"task validation is missing for {pair}")
        if decision.get("evaluator_validated") is not True:
            raise ValueError(f"evaluator validation is missing for {pair}")
        notes = decision.get("notes")
        if not isinstance(notes, str) or not notes.strip() or notes.startswith("REVIEW_"):
            raise ValueError(f"semantic review notes are missing for {pair}")
        approved.append(
            {
                "task_id": pair[0],
                "split": pair[1],
                "task_validated": True,
                "evaluator_validated": True,
                "task_prompt_sha256": candidate_row["task_prompt_sha256"],
                "test_sha256": candidate_row["test_sha256"],
                "review_notes": notes,
            }
        )
    return {
        "schema_version": 2,
        "status": "ready",
        "dataset": candidate["dataset"],
        "partition": candidate["partition"],
        "approved_pairs": approved,
        "review": {
            "candidate_sha256": review["candidate_sha256"],
            "reviewer_type": reviewer_type,
            "reviewer": reviewer,
            "reviewers": reviewers,
            "reviewed_at": reviewed_at,
            "no_model_outcomes_inspected": True,
            "scope": (
                "Each task specification, original evaluator, and same-input "
                "incompatible-output mutation received semantic review."
            ),
        },
    }


def write_json_new(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
