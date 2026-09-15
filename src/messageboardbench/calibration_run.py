"""Validation and sample construction for frozen prompt-calibration runs."""

from __future__ import annotations

import base64
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Callable

from messageboardbench.completion import completion_manifest_record
from messageboardbench.prompt_calibration import (
    DEFAULT_PARTITIONS,
    VARIANTS_BY_ID,
    apply_variant_to_sample,
    render_tools_instruction,
)


DATASET_PATH = "fjzzq2002/impossible_livecodebench"
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
ASSIGNMENT_FIELDS = {
    "task_id", "split", "prompt_variant", "replicate", "assignment_index"
}
ROOT = Path(__file__).resolve().parents[2]


def canonical_manifest_sha256(manifest: dict) -> str:
    payload = deepcopy(manifest)
    payload.pop("manifest_sha256", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def read_frozen_manifest(path: Path) -> tuple[dict, dict]:
    """Read and fully validate a development manifest before task loading."""
    source = Path(path)
    raw = source.read_bytes()
    manifest = json.loads(raw)
    if manifest.get("schema_version") != 1:
        raise ValueError("calibration manifest schema_version must be 1")
    if manifest.get("purpose") != "prompt-calibration-development-only":
        raise ValueError("manifest is not a development-only prompt-calibration plan")
    recorded = manifest.get("manifest_sha256")
    computed = canonical_manifest_sha256(manifest)
    if not isinstance(recorded, str) or not re.fullmatch(r"[0-9a-f]{64}", recorded):
        raise ValueError("manifest lacks a valid self-hash")
    if recorded != computed:
        raise ValueError("calibration manifest self-hash mismatch")
    validate_manifest(manifest)
    return manifest, {
        "path": str(source.resolve()),
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "manifest_sha256": recorded,
    }


def read_validation_audit(path: Path, manifest: dict) -> tuple[dict, dict]:
    """Verify semantic review and exact hashes for frozen validation pairs."""
    source = Path(path)
    raw = source.read_bytes()
    audit = json.loads(raw)
    if audit.get("schema_version") != 2 or audit.get("status") != "ready":
        raise ValueError("validation audit must be ready schema_version 2")
    if audit.get("partition") != "validation":
        raise ValueError("validation audit has the wrong partition")
    dataset = audit.get("dataset", {})
    if (dataset.get("path") != manifest["benchmark"]["dataset"]
            or dataset.get("revision") != manifest["benchmark"]["dataset_revision"]):
        raise ValueError("validation audit dataset mismatch")
    review = audit.get("review", {})
    reviewer_type = review.get("reviewer_type")
    if reviewer_type not in {"human", "internal_codex_dual_review"}:
        raise ValueError("validation audit lacks a permitted reviewer type")
    if not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
        raise ValueError("validation audit lacks a named reviewer or review group")
    if review.get("no_model_outcomes_inspected") is not True:
        raise ValueError("validation audit does not preserve the no-outcomes boundary")
    if reviewer_type == "internal_codex_dual_review":
        reviewers = review.get("reviewers")
        if not isinstance(reviewers, list) or len(reviewers) != 2:
            raise ValueError("internal validation audit requires two reviewer records")
        names, roles = set(), set()
        for reviewer in reviewers:
            if not isinstance(reviewer, dict):
                raise ValueError("internal validation reviewer record is malformed")
            names.add(reviewer.get("name"))
            roles.add(reviewer.get("role"))
            evidence_path = reviewer.get("evidence_path")
            evidence_hash = reviewer.get("evidence_sha256")
            if not isinstance(evidence_path, str) or not re.fullmatch(r"[0-9a-f]{64}", str(evidence_hash)):
                raise ValueError("internal validation review lacks evidence provenance")
            resolved = Path(evidence_path)
            if not resolved.is_absolute():
                resolved = ROOT / resolved
            if hashlib.sha256(resolved.read_bytes()).hexdigest() != evidence_hash:
                raise ValueError("internal validation review evidence hash mismatch")
        if len(names) != 2 or len(roles) != 2 or None in names or None in roles:
            raise ValueError("internal validation reviewers must have distinct names and roles")
    expected = {(row["task_id"], row["split"]) for row in manifest["validation_assignments"]}
    rows = audit.get("approved_pairs")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("validation audit approved pairs are malformed")
    indexed = {(row.get("task_id"), row.get("split")): row for row in rows}
    if len(indexed) != len(rows) or set(indexed) != expected:
        raise ValueError("validation audit must approve exactly the frozen validation pairs")
    for pair, row in indexed.items():
        if row.get("task_validated") is not True or row.get("evaluator_validated") is not True:
            raise ValueError(f"validation audit pair is not fully validated: {pair}")
        for field in ("task_prompt_sha256", "test_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(row.get(field, ""))):
                raise ValueError(f"validation audit pair lacks {field}: {pair}")
    return audit, {"path": str(source.resolve()), "sha256": hashlib.sha256(raw).hexdigest()}


def validate_manifest(manifest: dict) -> None:
    benchmark = manifest.get("benchmark", {})
    if benchmark.get("dataset") != DATASET_PATH:
        raise ValueError("unexpected calibration dataset")
    revision = str(benchmark.get("dataset_revision", "")).lower()
    if not COMMIT_RE.fullmatch(revision):
        raise ValueError("dataset revision must be a full 40-character hexadecimal commit")
    if benchmark.get("splits") != ["original", "conflicting"]:
        raise ValueError("calibration manifest must freeze original and conflicting splits")

    partitions = manifest.get("task_partitions", {})
    required_partitions = {"development", "validation", "communication_holdout"}
    if set(partitions) != required_partitions:
        raise ValueError("manifest must contain exactly the three task partitions")
    sets = {}
    for name in required_partitions:
        values = partitions[name]
        if not isinstance(values, list) or not values or len(values) != len(set(values)):
            raise ValueError(f"{name} partition must be non-empty and duplicate-free")
        sets[name] = set(values)
    if any(sets[left] & sets[right] for left, right in (
        ("development", "validation"),
        ("development", "communication_holdout"),
        ("validation", "communication_holdout"),
    )):
        raise ValueError("calibration task partitions overlap")

    variants = manifest.get("prompt_variants")
    if not isinstance(variants, list) or {row.get("variant_id") for row in variants} != set(VARIANTS_BY_ID):
        raise ValueError("development calibration must preserve all A-D prompt variants")
    for row in variants:
        variant_id = row["variant_id"]
        rendered = render_tools_instruction(variant_id)
        if row.get("rendered_tools_instruction") != rendered:
            raise ValueError(f"frozen prompt bytes differ from source variant {variant_id}")
        if row.get("rendered_tools_instruction_sha256") != hashlib.sha256(rendered.encode()).hexdigest():
            raise ValueError(f"frozen prompt hash differs for variant {variant_id}")

    environment = manifest.get("environment", {})
    expected_environment = {
        "communication": "none",
        "scratch": "fresh-private",
        "max_attempts": 3,
        "strict_tools": False,
        "sample_retries": 0,
        "request_retries": 1,
        "assignment_concurrency": 1,
        "completion_policy": completion_manifest_record(),
    }
    for field, expected in expected_environment.items():
        if environment.get(field) != expected:
            raise ValueError(f"unsupported calibration environment field: {field}")
    model = environment.get("model")
    if not isinstance(model, str) or not model.startswith("openrouter/") or len(model.split("/")) < 3:
        raise ValueError("manifest model must be a full openrouter/provider/model identifier")
    for field in ("message_limit", "token_limit", "time_limit_seconds"):
        if not isinstance(environment.get(field), int) or environment[field] < 1:
            raise ValueError(f"manifest {field} must be a positive integer")
    temperature = environment.get("temperature")
    if not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
        raise ValueError("manifest temperature must be between 0 and 2")
    if environment.get("reasoning_effort") not in {
        "none", "minimal", "low", "medium", "high", "xhigh"
    }:
        raise ValueError("manifest has unsupported reasoning effort")

    assignments = manifest.get("development_assignments")
    if not isinstance(assignments, list) or not assignments:
        raise ValueError("manifest has no development assignments")
    expected_indices = list(range(1, len(assignments) + 1))
    if [row.get("assignment_index") for row in assignments] != expected_indices:
        raise ValueError("development assignment indices must be contiguous and ordered")
    if any(set(row) != ASSIGNMENT_FIELDS for row in assignments):
        raise ValueError("development assignment fields differ from the frozen schema")
    if any(row["task_id"] not in sets["development"] for row in assignments):
        raise ValueError("development assignment includes a non-development task")
    forbidden = sets["communication_holdout"] | set(DEFAULT_PARTITIONS.communication_holdout)
    if any(row["task_id"] in forbidden for row in assignments):
        raise ValueError("communication holdout task appears in development assignments")
    if any(row["split"] not in ("original", "conflicting") for row in assignments):
        raise ValueError("development assignment has an unsupported split")
    if any(row["prompt_variant"] not in VARIANTS_BY_ID for row in assignments):
        raise ValueError("development assignment has an unsupported prompt variant")
    if any(not isinstance(row["replicate"], int) or row["replicate"] < 1 for row in assignments):
        raise ValueError("development replicate values must be positive integers")

    replicates = manifest.get("randomization", {}).get("replicates_per_task_variant")
    if not isinstance(replicates, int) or replicates < 1:
        raise ValueError("manifest has an invalid replicate count")
    actual = Counter(
        (row["task_id"], row["split"], row["prompt_variant"], row["replicate"])
        for row in assignments
    )
    expected = Counter(
        (task_id, split, variant_id, replicate)
        for task_id in partitions["development"]
        for split in ("original", "conflicting")
        for variant_id in VARIANTS_BY_ID
        for replicate in range(1, replicates + 1)
    )
    if actual != expected:
        raise ValueError("development assignments are not the complete frozen crossing")

    validation_assignments = manifest.get("validation_assignments")
    if not isinstance(validation_assignments, list) or not validation_assignments:
        raise ValueError("manifest has no validation assignments")
    validation_indices = list(range(1, len(validation_assignments) + 1))
    if [row.get("assignment_index") for row in validation_assignments] != validation_indices:
        raise ValueError("validation assignment indices must be contiguous and ordered")
    if any(not isinstance(row, dict) or set(row) != ASSIGNMENT_FIELDS for row in validation_assignments):
        raise ValueError("validation assignment fields differ from the frozen schema")
    if any(row["task_id"] not in sets["validation"] for row in validation_assignments):
        raise ValueError("validation assignment includes a non-validation task")
    if any(row["task_id"] in forbidden for row in validation_assignments):
        raise ValueError("communication holdout task appears in validation assignments")
    if any(row["split"] not in ("original", "conflicting") for row in validation_assignments):
        raise ValueError("validation assignment has an unsupported split")
    if any(row["prompt_variant"] != "D" for row in validation_assignments):
        raise ValueError("validation assignments must use only preselected prompt D")
    if any(not isinstance(row["replicate"], int) or row["replicate"] < 1 for row in validation_assignments):
        raise ValueError("validation replicate values must be positive integers")
    validation_actual = Counter(
        (row["task_id"], row["split"], row["prompt_variant"], row["replicate"])
        for row in validation_assignments
    )
    validation_expected = Counter(
        (task_id, split, "D", replicate)
        for task_id in partitions["validation"]
        for split in ("original", "conflicting")
        for replicate in range(1, replicates + 1)
    )
    if validation_actual != validation_expected:
        raise ValueError("validation assignments are not the complete frozen prompt-D crossing")


def load_pinned_datasets(revision: str) -> dict[str, dict[str, object]]:
    from inspect_ai.dataset import hf_dataset
    from impossiblebench.livecodebench_tasks import (
        INSTRUCTION,
        INSTRUCTION_SUFFIX_TOOLS,
        record_to_sample,
    )

    if not COMMIT_RE.fullmatch(revision):
        raise ValueError("dataset revision must be immutable")
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


def prepare_development_samples(
    manifest: dict,
    manifest_source: dict,
    *,
    loader: Callable[[str], dict[str, dict[str, object]]] = load_pinned_datasets,
) -> list[dict]:
    """Construct exact assignment samples and attach complete run provenance."""
    revision = manifest["benchmark"]["dataset_revision"]
    datasets = loader(revision)
    completion = completion_manifest_record()
    prepared = []
    for assignment in manifest["development_assignments"]:
        task_id, split = assignment["task_id"], assignment["split"]
        try:
            source = datasets[split][task_id]
        except KeyError as exc:
            raise ValueError(f"pinned dataset is missing {split}/{task_id}") from exc
        sample = apply_variant_to_sample(source, assignment["prompt_variant"])
        rendered = render_tools_instruction(assignment["prompt_variant"])
        if sample.input != rendered or sample.metadata.get("instruction_prompt") != rendered:
            raise ValueError("prepared sample differs from its frozen rendered prompt")
        prompt_bytes = rendered.encode("utf-8")
        task_prompt = sample.metadata.get("prompt")
        test = sample.metadata.get("test")
        if not isinstance(task_prompt, str) or not isinstance(test, str):
            raise ValueError(f"pinned dataset has non-text fields for {split}/{task_id}")
        provenance = {
            "phase": "development",
            "communication": "none",
            "assignment": dict(assignment),
            "manifest": dict(manifest_source),
            "dataset": {"path": DATASET_PATH, "revision": revision, "split": split},
            "policy_prompt": {
                "variant": assignment["prompt_variant"],
                "rendered_instruction_prompt": rendered,
                "rendered_instruction_prompt_encoding": "utf-8",
                "rendered_instruction_prompt_base64": base64.b64encode(prompt_bytes).decode("ascii"),
                "rendered_instruction_prompt_bytes": len(prompt_bytes),
                "rendered_instruction_prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
            },
            "task_prompt_sha256": hashlib.sha256(task_prompt.encode()).hexdigest(),
            "test_sha256": hashlib.sha256(test.encode()).hexdigest(),
            "completion": completion,
        }
        sample.metadata = dict(sample.metadata or {})
        sample.metadata["calibration"] = provenance
        sample.metadata["completion"] = completion
        prepared.append({"assignment": assignment, "sample": sample, "provenance": provenance})
    return prepared


def prepare_validation_samples(
    manifest: dict,
    manifest_source: dict,
    *,
    loader: Callable[[str], dict[str, dict[str, object]]] = load_pinned_datasets,
) -> list[dict]:
    """Construct only the frozen one-shot prompt-D validation assignments."""
    revision = manifest["benchmark"]["dataset_revision"]
    datasets = loader(revision)
    completion = completion_manifest_record()
    prepared = []
    for assignment in manifest["validation_assignments"]:
        if assignment["prompt_variant"] != "D":
            raise ValueError("validation execution is restricted to prompt D")
        task_id, split = assignment["task_id"], assignment["split"]
        try:
            source = datasets[split][task_id]
        except KeyError as exc:
            raise ValueError(f"pinned dataset is missing validation pair {split}/{task_id}") from exc
        sample = apply_variant_to_sample(source, "D")
        rendered = render_tools_instruction("D")
        if sample.input != rendered or sample.metadata.get("instruction_prompt") != rendered:
            raise ValueError("prepared validation sample differs from frozen prompt D")
        task_prompt = sample.metadata.get("prompt")
        test = sample.metadata.get("test")
        if not isinstance(task_prompt, str) or not isinstance(test, str):
            raise ValueError(f"pinned dataset has non-text fields for {split}/{task_id}")
        prompt_bytes = rendered.encode("utf-8")
        provenance = {
            "phase": "validation",
            "communication": "none",
            "assignment": dict(assignment),
            "manifest": dict(manifest_source),
            "dataset": {"path": DATASET_PATH, "revision": revision, "split": split},
            "policy_prompt": {
                "variant": "D",
                "rendered_instruction_prompt": rendered,
                "rendered_instruction_prompt_encoding": "utf-8",
                "rendered_instruction_prompt_base64": base64.b64encode(prompt_bytes).decode("ascii"),
                "rendered_instruction_prompt_bytes": len(prompt_bytes),
                "rendered_instruction_prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
            },
            "task_prompt_sha256": hashlib.sha256(task_prompt.encode()).hexdigest(),
            "test_sha256": hashlib.sha256(test.encode()).hexdigest(),
            "completion": completion,
        }
        sample.metadata = dict(sample.metadata or {})
        sample.metadata["calibration"] = provenance
        sample.metadata["completion"] = completion
        prepared.append({"assignment": assignment, "sample": sample, "provenance": provenance})
    return prepared
