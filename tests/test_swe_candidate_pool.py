from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
import subprocess

import pytest

from messageboardbench.swe_validation import TrialResult, ValidationError
from messageboardbench.swe_board import canonical_hash, plan_hash
from messageboardbench.swe_candidate_pool import (
    RANKING_NAMESPACE,
    PRE_POOL_OBSERVATION,
    candidate_order,
    file_sha256,
    make_decision,
    make_ledger,
    object_sha256,
    rejection_reason,
    validate_candidate_pool,
    validate_decision,
)
from scripts import prepare_swe_population_v3 as prepare


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def frozen_plan(**fields):
    value = {"schema_version": 1, "status": "frozen", **fields}
    value["plan_sha256"] = plan_hash(value)
    return value


def pool_fixture(tmp_path):
    dataset = {"path": "fjzzq2002/impossible_swebench", "revision": "1" * 40,
               "split": "conflicting"}
    hashes = {f"task-{index}": hashlib.sha256(str(index).encode()).hexdigest()
              for index in range(12)}
    population = frozen_plan(
        purpose="population-propensity-control-vs-board-swe", dataset=dataset,
        instance_count=len(hashes), records_sha256=hashes,
    )
    priority = ["task-3", "task-1"]
    v2 = frozen_plan(
        purpose="population-propensity-control-vs-board-swe-pilot-v2",
        dataset=dataset, selection={"instance_ids": priority},
    )
    population_path = tmp_path / "population.json"
    v2_path = tmp_path / "v2.json"
    write(population_path, population)
    write(v2_path, v2)
    order = candidate_order(priority, hashes, 910)
    pool = {
        "schema_version": 1, "status": "frozen",
        "purpose": "swe-population-pilot-v3-candidate-pool",
        "dataset": dataset, "target_pass_count": 10, "seed": 910,
        "ranking_namespace": RANKING_NAMESPACE,
        "priority_instance_ids": priority, "candidate_count": len(hashes),
        "candidate_order_sha256": canonical_hash(order),
        "records_sha256_sha256": canonical_hash(hashes),
        "original_records_sha256_sha256": "original-map-hash",
        "pre_pool_observation": PRE_POOL_OBSERVATION,
        "population_source": {"path": "population.json",
                              "file_sha256": file_sha256(population_path),
                              "plan_sha256": population["plan_sha256"]},
        "priority_source": {"path": "v2.json", "file_sha256": file_sha256(v2_path),
                            "plan_sha256": v2["plan_sha256"]},
    }
    pool["sha256"] = object_sha256(pool)
    return pool, order


def test_pool_replays_v2_first_then_ranked_unused_and_binds_sources(tmp_path):
    pool, expected = pool_fixture(tmp_path)
    order, population = validate_candidate_pool(pool, tmp_path)
    assert order == expected
    assert order[:2] == ["task-3", "task-1"]
    assert len(order) == len(set(order)) == 12
    assert set(order) == set(population["records_sha256"])

    source = tmp_path / "population.json"
    changed = json.loads(source.read_text())
    changed["records_sha256"]["task-0"] = "changed"
    write(source, changed)
    with pytest.raises(ValueError, match="source file hash"):
        validate_candidate_pool(pool, tmp_path)


def test_pool_order_or_hash_mutation_is_rejected(tmp_path):
    pool, _ = pool_fixture(tmp_path)
    pool["priority_instance_ids"] = list(reversed(pool["priority_instance_ids"]))
    pool["sha256"] = object_sha256(pool)
    with pytest.raises(ValueError, match="prioritize"):
        validate_candidate_pool(pool, tmp_path)

    pool, _ = pool_fixture(tmp_path)
    pool["pre_pool_observation"] = {**PRE_POOL_OBSERVATION, "disclosure": "changed"}
    pool["sha256"] = object_sha256(pool)
    with pytest.raises(ValueError, match="identity"):
        validate_candidate_pool(pool, tmp_path)


def test_ledger_selects_first_ten_passes_and_binds_all_prior_rejections():
    pool = {"sha256": "pool", "target_pass_count": 10}
    decisions = []
    for index in range(12):
        passed = index not in {0, 4}
        fields = dict(pool_sha256="pool", candidate_index=index,
                      instance_id=f"task-{index}", status="passed" if passed else "rejected",
                      evidence={"directory": "evidence", "results": []})
        if passed:
            fields["manifest"] = {"path": f"task-{index}/manifest.json",
                                  "sha256": f"manifest-{index}"}
        else:
            fields["reason"] = "missing/error targets"
        decisions.append(make_decision(**fields))
    ledger = make_ledger(pool, decisions)
    assert ledger["selected_instance_ids"] == [
        "task-1", "task-2", "task-3", "task-5", "task-6",
        "task-7", "task-8", "task-9", "task-10", "task-11",
    ]
    assert len(ledger["decisions"]) == 12
    assert ledger["sha256"] == object_sha256(ledger)


def trial(status="MISSING"):
    return TrialResult(
        split="original", mode="nochange", exit_code=1,
        output_file="original-nochange.txt",
        output_sha256=hashlib.sha256(b"output").hexdigest(), image="repo:tag",
        image_id="sha256:image", repo_digests=["repo@sha256:digest"],
        test_command=["pytest"], target_statuses={"target": status}, resolved=False,
    )


@pytest.mark.parametrize(
    ("status", "reason_fragment"),
    [("MISSING", "contains MISSING/ERROR"), ("PASSED", "has no FAILED target")],
)
def test_bad_false_cell_becomes_rejection_after_one_cell(
    tmp_path, monkeypatch, status, reason_fragment
):
    monkeypatch.setattr(prepare, "ROOT", tmp_path)
    monkeypatch.setattr(prepare, "swebench_spec", lambda record: ("repo:tag", [], "pytest"))
    monkeypatch.setattr(prepare, "pull_image_once", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        prepare, "cleanup_candidate_image",
        lambda *args, **kwargs: {"path": "cleanup.json", "file_sha256": "file", "sha256": "cleanup"},
    )
    calls = []

    def run_trial(*args, **kwargs):
        calls.append((kwargs["split"], kwargs["mode"]))
        kwargs["out_dir"].joinpath("original-nochange.txt").write_text("output")
        return trial(status)

    monkeypatch.setattr(prepare, "run_trial", run_trial)
    pool = {"sha256": "pool", "candidate_count": 12,
            "dataset": {"revision": "1" * 40},
            "parameters": {"memory": "8g", "scorer_timeout_seconds": 1}}
    decision = prepare.decide_candidate(
        pool=pool, population={"records_sha256": {}}, index=0, instance_id="task",
        original={}, conflicting={}, screen_root=tmp_path / "screen",
        pulled_images=set(), environ={},
    )
    assert decision["status"] == "rejected"
    assert reason_fragment in decision["reason"]
    assert calls == [("original", "nochange")]


def test_infrastructure_failure_is_not_converted_to_candidate_rejection(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare, "ROOT", tmp_path)
    monkeypatch.setattr(prepare, "swebench_spec", lambda record: ("repo:tag", [], "pytest"))
    monkeypatch.setattr(prepare, "pull_image_once", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        prepare, "cleanup_candidate_image",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValidationError("cleanup unavailable")),
    )
    monkeypatch.setattr(
        prepare, "run_trial",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValidationError("daemon unavailable")),
    )
    pool = {"sha256": "pool", "candidate_count": 12,
            "dataset": {"revision": "1" * 40},
            "parameters": {"memory": "8g", "scorer_timeout_seconds": 1}}
    with pytest.raises(ValidationError, match="daemon unavailable"):
        prepare.decide_candidate(
            pool=pool, population={"records_sha256": {}}, index=0, instance_id="task",
            original={}, conflicting={}, screen_root=tmp_path / "screen",
            pulled_images=set(), environ={},
        )


def test_screen_loader_fetches_each_split_once_and_checks_both_hash_maps(monkeypatch):
    originals = {"task": {"instance_id": "task", "split": "original"}}
    conflicting = {"task": {"instance_id": "task", "split": "conflicting"}}
    calls = []

    def loader(revision, split):
        calls.append((revision, split))
        return originals if split == "original" else conflicting

    monkeypatch.setattr(prepare, "load_records", loader)
    monkeypatch.setattr(prepare, "validate_pair", lambda *args: None)
    pool = {
        "dataset": {"revision": "1" * 40}, "priority_instance_ids": ["task"],
        "seed": 910,
        "original_records_sha256_sha256": canonical_hash(
            {"task": canonical_hash(originals["task"])}
        ),
    }
    population = {"records_sha256": {"task": canonical_hash(conflicting["task"])}}
    order, loaded_originals, loaded_conflicting = prepare.load_screen_records(pool, population)
    assert calls == [("1" * 40, "original"), ("1" * 40, "conflicting")]
    assert order == ["task"]
    assert loaded_originals is originals
    assert loaded_conflicting is conflicting


def result_rows(tmp_path, statuses=("FAILED", "PASSED", "FAILED", "FAILED"),
                resolved=(False, True, False, False)):
    rows = []
    cells = [("original", "nochange"), ("original", "oracle"),
             ("conflicting", "nochange"), ("conflicting", "oracle")]
    for index, ((split, mode), status, outcome) in enumerate(zip(cells, statuses, resolved)):
        name = f"cell-{index}.txt"
        (tmp_path / name).write_text("output")
        value = asdict(trial(status))
        value.update(split=split, mode=mode, resolved=outcome, output_file=name)
        rows.append(value)
    return rows


def rejected_decision(instance_id, rows, cleanup, *, imported=False):
    reason = rejection_reason(rows, imported_pre_pool=imported)
    fields = dict(
        pool_sha256="pool", candidate_index=0, instance_id=instance_id,
        status="rejected", reason=reason,
        evidence={"directory": "evidence", "results": rows},
        image_cleanup=cleanup,
    )
    if imported:
        fields["pre_pool_observation"] = True
    return make_decision(**fields)


def test_rejected_receipt_requires_observed_frozen_ground(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    eligible = result_rows(evidence)
    with pytest.raises(ValueError, match="eligible matrix"):
        rejection_reason(eligible)
    with pytest.raises(ValueError, match="unfinished eligible prefix"):
        rejection_reason(eligible[:1])
    missing = result_rows(evidence, statuses=("PASSED", "MISSING", "PASSED", "PASSED"))
    with pytest.raises(ValueError, match="continued after"):
        rejection_reason(missing)
    assert rejection_reason(
        result_rows(evidence, statuses=("PASSED",))[:1]
    ) == "target-status rejection: original/nochange has no FAILED target"
    wrong = result_rows(evidence, resolved=(True, True, False, False))
    assert rejection_reason(wrong).startswith("outcome-matrix rejection")


def test_imported_legacy_full_missing_matrix_passes_rejection_replay(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    rows = result_rows(
        evidence, statuses=("PASSED", "PASSED", "MISSING", "MISSING")
    )
    cleanup_value = {
        "schema_version": 1, "instance_id": PRE_POOL_OBSERVATION["instance_id"],
        "image": "repo:tag", "complete": True,
    }
    cleanup_value["sha256"] = object_sha256(cleanup_value)
    cleanup_path = tmp_path / "cleanup.json"
    write(cleanup_path, cleanup_value)
    cleanup = {"path": "cleanup.json", "file_sha256": file_sha256(cleanup_path),
               "sha256": cleanup_value["sha256"]}
    decision = rejected_decision(
        PRE_POOL_OBSERVATION["instance_id"], rows, cleanup, imported=True
    )
    validate_decision(
        decision, pool={"sha256": "pool"}, index=0,
        instance_id=PRE_POOL_OBSERVATION["instance_id"], root=tmp_path,
        record={}, plan_like={},
    )
    decision["reason"] = "arbitrary"
    decision["sha256"] = object_sha256(decision)
    with pytest.raises(ValueError, match="ground mismatch"):
        validate_decision(
            decision, pool={"sha256": "pool"}, index=0,
            instance_id=PRE_POOL_OBSERVATION["instance_id"], root=tmp_path,
            record={}, plan_like={},
        )


def test_atomic_write_never_replaces_and_cleans_failed_temporary(tmp_path, monkeypatch):
    path = tmp_path / "receipt.json"
    prepare.write_new(path, {"value": 1})
    with pytest.raises(FileExistsError):
        prepare.write_new(path, {"value": 2})
    assert json.loads(path.read_text()) == {"value": 1}
    assert not list(tmp_path.glob(".receipt.json.tmp-*"))

    failed = tmp_path / "failed.json"
    monkeypatch.setattr(prepare.os, "link", lambda *args: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError, match="crash"):
        prepare.write_new(failed, {"value": 3})
    assert not failed.exists()
    assert not list(tmp_path.glob(".failed.json.tmp-*"))


def test_rejected_candidate_image_cleanup_is_recorded_and_repullable(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare, "ROOT", tmp_path)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(argv, 0, '{"Id":"sha256:image"}', "")
        return subprocess.CompletedProcess(argv, 0, "untagged", "")

    pulled = {"repo:tag"}
    path = tmp_path / "cleanup.json"
    reference = prepare.cleanup_candidate_image(
        "task", "repo:tag", path, pulled, {}, run=run
    )
    assert calls == [
        ["docker", "image", "inspect", "repo:tag", "--format", "{{json .}}"],
        ["docker", "image", "rm", "repo:tag"],
    ]
    assert json.loads(path.read_text())["complete"] is True
    assert reference["file_sha256"] == file_sha256(path)
    assert "repo:tag" not in pulled
