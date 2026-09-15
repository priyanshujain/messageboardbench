import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from messageboardbench.holdout_audit import (
    COMMUNICATION_HOLDOUT,
    build_candidate,
    candidate_review_template,
    freeze_reviewed_audit,
    validate_revision,
)


REVISION = "b" * 40
ROOT = Path(__file__).parents[1]


def samples(revision):
    assert revision == REVISION
    result = {"original": {}, "conflicting": {}}
    for index, task_id in enumerate(COMMUNICATION_HOLDOUT):
        call = f"candidate({index})"
        common = {
            "prompt": f"Specification {task_id}",
            "entry_point": "candidate",
        }
        original_test = f"def check(candidate):\n    assert {call} == {index}\n"
        conflicting_test = (
            f"def check(candidate):\n"
            f"    assert {call} == {index + 1}\n"
            f"    assert {call} == {index}\n"
        )
        result["original"][task_id] = SimpleNamespace(
            metadata={**common, "test": original_test}
        )
        result["conflicting"][task_id] = SimpleNamespace(
            metadata={**common, "test": conflicting_test}
        )
    return result


def encoded_candidate():
    candidate = build_candidate(REVISION, loader=samples)
    return candidate, (json.dumps(candidate, indent=2, sort_keys=True) + "\n").encode()


def completed_review(candidate_bytes):
    review = candidate_review_template(candidate_bytes)
    review["reviewer"] = "PJ"
    review["reviewed_at"] = "2026-09-09T12:00:00+05:30"
    for decision in review["decisions"]:
        decision["task_validated"] = True
        decision["evaluator_validated"] = True
        decision["notes"] = "Reviewed specification, original answers, and contradictory pair."
    return review


def completed_dual_review(candidate_bytes):
    review = completed_review(candidate_bytes)
    review["reviewer_type"] = "internal_codex_dual_review"
    review["reviewer"] = "Codex internal dual technical review"
    review["reviewers"] = [
        {
            "name": "lcb_semantic_review",
            "role": "primary_semantic_review",
            "evidence_path": "work/lcb-holdout-semantic-review.md",
            "evidence_sha256": hashlib.sha256(
                (ROOT / "work/lcb-holdout-semantic-review.md").read_bytes()
            ).hexdigest(),
        },
        {
            "name": "lcb_crossreview",
            "role": "blind_cross_review",
            "evidence_path": "work/lcb-holdout-crossreview.md",
            "evidence_sha256": hashlib.sha256(
                (ROOT / "work/lcb-holdout-crossreview.md").read_bytes()
            ).hexdigest(),
        },
    ]
    return review


def test_candidate_is_not_ready_and_records_mechanical_evidence_only():
    candidate, _ = encoded_candidate()
    assert candidate["schema_version"] == 2
    assert candidate["status"] == "needs_semantic_review"
    assert candidate["all_mechanical_checks_pass"] is True
    assert [row["task_id"] for row in candidate["candidate_pairs"]] == list(
        COMMUNICATION_HOLDOUT
    )
    for row in candidate["candidate_pairs"]:
        assert all(row["automated_checks"].values())
        assert row["contradiction_evidence"][
            "same_call_incompatible_expected_value_count"
        ] == 1
        assert row["review_material"]["task_prompt"].startswith("Specification")
        assert "assert candidate" in row["review_material"]["original_test"]
        assert "task_validated" not in row
        assert "evaluator_validated" not in row


def test_candidate_rejects_non_commit_and_non_holdout_ids():
    with pytest.raises(ValueError, match="40-character"):
        validate_revision("main")
    with pytest.raises(ValueError, match="outside communication holdout"):
        build_candidate(REVISION, task_ids=("lcbhard_0",), loader=samples)


def test_validation_candidate_reviews_both_frozen_splits():
    task_id = "lcbhard_3"
    def validation_samples(revision):
        common = {"prompt": "Specification", "entry_point": "candidate"}
        return {
            "original": {task_id: SimpleNamespace(metadata={
                **common, "test": "def check(candidate):\n assert candidate(1) == 1\n",
            })},
            "conflicting": {task_id: SimpleNamespace(metadata={
                **common, "test": (
                    "def check(candidate):\n assert candidate(1) == 2\n"
                    " assert candidate(1) == 1\n"
                ),
            })},
        }
    candidate = build_candidate(
        REVISION, task_ids=(task_id,), partition="validation", loader=validation_samples,
    )
    assert candidate["partition"] == "validation"
    assert {(row["task_id"], row["split"]) for row in candidate["candidate_pairs"]} == {
        (task_id, "original"), (task_id, "conflicting"),
    }


@pytest.mark.parametrize(
    ("original_test", "conflicting_test", "expected"),
    [
        (
            "def check(candidate):\n assert candidate(1) is None\n",
            "def check(candidate):\n assert candidate(1) is None\n assert candidate(1) is not None\n",
            "is not None",
        ),
        (
            "def check(candidate):\n assert candidate(1) is None\n",
            "def check(candidate):\n assert candidate(1) is None\n"
            " result = candidate(1)\n assert result is not None\n"
            " assert len(result) == 9\n",
            "is not None",
        ),
    ],
)
def test_candidate_detects_identity_contradiction_direct_or_through_simple_assignment(
    original_test, conflicting_test, expected,
):
    task_id = "lcbhard_3"

    def validation_samples(revision):
        common = {"prompt": "Specification", "entry_point": "candidate"}
        return {
            "original": {task_id: SimpleNamespace(metadata={**common, "test": original_test})},
            "conflicting": {
                task_id: SimpleNamespace(metadata={**common, "test": conflicting_test})
            },
        }

    candidate = build_candidate(
        REVISION, task_ids=(task_id,), partition="validation", loader=validation_samples,
    )
    assert candidate["all_mechanical_checks_pass"] is True
    evidence = candidate["candidate_pairs"][0]["contradiction_evidence"]
    assert evidence["added_assertion_count"] == 1
    assert evidence["same_call_incompatible_expected_value_count"] == 1
    assert evidence["same_call_incompatible_expected_values"][0]["conflicting_expected"] == expected


def test_candidate_assignment_dataflow_fails_closed_on_rebinding():
    task_id = "lcbhard_3"

    def validation_samples(revision):
        common = {"prompt": "Specification", "entry_point": "candidate"}
        original = "def check(candidate):\n assert candidate(1) is None\n"
        conflicting = (
            "def check(candidate):\n assert candidate(1) is None\n"
            " result = candidate(1)\n result = object()\n assert result is not None\n"
        )
        return {
            "original": {task_id: SimpleNamespace(metadata={**common, "test": original})},
            "conflicting": {task_id: SimpleNamespace(metadata={**common, "test": conflicting})},
        }

    candidate = build_candidate(
        REVISION, task_ids=(task_id,), partition="validation", loader=validation_samples,
    )
    assert candidate["all_mechanical_checks_pass"] is False


def test_candidate_flags_failed_mechanical_check_without_claiming_readiness():
    def bad_samples(revision):
        loaded = samples(revision)
        task_id = COMMUNICATION_HOLDOUT[0]
        loaded["conflicting"][task_id].metadata["test"] = loaded["original"][
            task_id
        ].metadata["test"]
        return loaded

    candidate = build_candidate(REVISION, loader=bad_samples)
    assert candidate["status"] == "needs_semantic_review"
    assert candidate["all_mechanical_checks_pass"] is False


def test_freeze_requires_exact_candidate_bytes_and_explicit_semantic_approval():
    candidate, candidate_bytes = encoded_candidate()
    template = candidate_review_template(candidate_bytes)
    with pytest.raises(ValueError, match="name its reviewer"):
        freeze_reviewed_audit(candidate_bytes, template)

    review = completed_review(candidate_bytes)
    with pytest.raises(ValueError, match="exact candidate bytes"):
        freeze_reviewed_audit(candidate_bytes + b" ", review)

    review = completed_review(candidate_bytes)
    review["decisions"][0]["evaluator_validated"] = False
    with pytest.raises(ValueError, match="evaluator validation"):
        freeze_reviewed_audit(candidate_bytes, review)

    # Candidate mechanical failures cannot be overridden by a reviewer.
    candidate["all_mechanical_checks_pass"] = False
    failed_bytes = (json.dumps(candidate, indent=2, sort_keys=True) + "\n").encode()
    with pytest.raises(ValueError, match="failed mechanical"):
        freeze_reviewed_audit(failed_bytes, completed_review(failed_bytes))


def test_freeze_accepts_named_internal_codex_dual_review():
    _, candidate_bytes = encoded_candidate()
    ready = freeze_reviewed_audit(candidate_bytes, completed_dual_review(candidate_bytes))
    assert ready["schema_version"] == 2
    assert ready["review"]["reviewer_type"] == "internal_codex_dual_review"
    assert [row["name"] for row in ready["review"]["reviewers"]] == [
        "lcb_semantic_review",
        "lcb_crossreview",
    ]


def test_dual_review_requires_two_distinct_named_evidence_records():
    _, candidate_bytes = encoded_candidate()
    review = completed_dual_review(candidate_bytes)
    review["reviewers"].pop()
    with pytest.raises(ValueError, match="exactly two"):
        freeze_reviewed_audit(candidate_bytes, review)

    review = completed_dual_review(candidate_bytes)
    review["reviewers"][1]["name"] = review["reviewers"][0]["name"]
    with pytest.raises(ValueError, match="distinct reviewer"):
        freeze_reviewed_audit(candidate_bytes, review)

    review = completed_dual_review(candidate_bytes)
    review["reviewers"][1]["evidence_sha256"] = "not-a-hash"
    with pytest.raises(ValueError, match="valid SHA-256"):
        freeze_reviewed_audit(candidate_bytes, review)


def test_ready_output_matches_board_pilot_input_schema(tmp_path):
    _, candidate_bytes = encoded_candidate()
    ready = freeze_reviewed_audit(candidate_bytes, completed_dual_review(candidate_bytes))
    assert ready["status"] == "ready"
    assert ready["review"]["reviewer_type"] == "internal_codex_dual_review"
    assert len(ready["approved_pairs"]) == len(COMMUNICATION_HOLDOUT)

    path = tmp_path / "ready.json"
    raw = (json.dumps(ready, indent=2) + "\n").encode()
    path.write_bytes(raw)
    spec = importlib.util.spec_from_file_location(
        "board_pilot_for_audit_test", Path(__file__).parents[1] / "scripts/board_pilot.py"
    )
    board_pilot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(board_pilot)
    audit, source = board_pilot.read_holdout_audit(
        path,
        REVISION,
        [(task_id, "conflicting") for task_id in COMMUNICATION_HOLDOUT],
    )
    assert audit == ready
    assert source["sha256"] == hashlib.sha256(raw).hexdigest()
