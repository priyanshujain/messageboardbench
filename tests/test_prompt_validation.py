from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from inspect_ai.dataset import Sample

from messageboardbench.calibration_run import prepare_validation_samples
from messageboardbench.prompt_calibration import TaskPartitions, build_manifest, render_tools_instruction


REVISION = "e" * 40
PROMPT = "def candidate(x): pass"
TEST = "def check(candidate): pass"


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "run_prompt_validation", Path(__file__).parents[1] / "scripts/run_prompt_validation.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plan_fixture(tmp_path: Path):
    partitions = TaskPartitions(
        development=("dev",), validation=("val",), communication_holdout=("hold",),
    )
    manifest = build_manifest(dataset_revision=REVISION, partitions=partitions)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(manifest))
    audit = tmp_path / "validation-audit.json"
    pairs = {(row["task_id"], row["split"]) for row in manifest["validation_assignments"]}
    audit.write_text(json.dumps({
        "schema_version": 2, "status": "ready", "partition": "validation",
        "dataset": {"path": manifest["benchmark"]["dataset"], "revision": REVISION},
        "review": {"reviewer_type": "human", "reviewer": "Test reviewer",
                   "no_model_outcomes_inspected": True},
        "approved_pairs": [{
            "task_id": task_id, "split": split, "task_validated": True,
            "evaluator_validated": True,
            "task_prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
            "test_sha256": hashlib.sha256(TEST.encode()).hexdigest(),
        } for task_id, split in sorted(pairs)],
    }))
    return manifest, path, audit


def sample_loader(revision):
    base = render_tools_instruction("A")
    return {split: {"val": Sample(
        id="val", input=base, metadata={"instruction_prompt": base, "prompt": PROMPT,
                                        "test": TEST, "entry_point": "candidate"},
    )} for split in ("original", "conflicting")}


def test_prepare_validation_uses_only_validation_d():
    manifest = build_manifest(
        dataset_revision=REVISION,
        partitions=TaskPartitions(development=("dev",), validation=("val",),
                                  communication_holdout=("hold",)),
    )
    source = {"path": "/plan", "file_sha256": "a" * 64,
              "manifest_sha256": manifest["manifest_sha256"]}
    prepared = prepare_validation_samples(manifest, source, loader=sample_loader)
    assert {row["assignment"]["task_id"] for row in prepared} == {"val"}
    assert {row["assignment"]["prompt_variant"] for row in prepared} == {"D"}
    assert all(row["sample"].metadata["calibration"]["phase"] == "validation"
               for row in prepared)


def test_preview_is_offline_and_does_not_consume(tmp_path, monkeypatch, capsys):
    runner = load_runner()
    _, plan, audit = plan_fixture(tmp_path)
    out = tmp_path / "run"
    monkeypatch.setattr(runner, "prepare_validation_samples",
                        lambda *args: pytest.fail("preview loaded dataset"))
    monkeypatch.setattr(runner, "LEDGER_DIR", tmp_path / "ledger")
    assert runner.main(["--manifest", str(plan), "--validation-audit", str(audit),
                        "--out", str(out)]) == 0
    assert "Preview only" in capsys.readouterr().out
    assert not out.exists() and not (tmp_path / "ledger").exists()


def test_execute_requires_remote_docker_before_dataset(tmp_path, monkeypatch):
    runner = load_runner()
    _, plan, audit = plan_fixture(tmp_path)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(runner, "prepare_validation_samples",
                        lambda *args: pytest.fail("wrong host loaded dataset"))
    with pytest.raises(RuntimeError, match="remote Docker daemon"):
        runner.main(["--manifest", str(plan), "--validation-audit", str(audit),
                     "--out", str(tmp_path / "run"), "--execute"])


def test_mock_execution_writes_gate_compatible_run_and_is_one_shot(tmp_path, monkeypatch):
    runner = load_runner()
    manifest, plan, audit = plan_fixture(tmp_path)
    monkeypatch.setattr(
        runner, "prepare_validation_samples",
        lambda loaded, source: prepare_validation_samples(loaded, source, loader=sample_loader),
    )
    monkeypatch.setattr(runner, "LEDGER_DIR", tmp_path / "ledger")
    monkeypatch.setenv("DOCKER_HOST", runner.REMOTE_DOCKER_HOST)
    budgets = iter([{"usage": 1, "limit": 5, "limit_remaining": 4},
                    {"usage": 1.1, "limit": 5, "limit_remaining": 3.9}])
    monkeypatch.setattr(runner, "budget", lambda: next(budgets))
    import inspect_ai
    import messageboardbench.board_task as board_task
    import messageboardbench.task as task_module
    monkeypatch.setattr(inspect_ai, "Task", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(board_task, "episode_solver", lambda *args, **kwargs: "solver")
    monkeypatch.setattr(task_module, "scratch_scorer", lambda split: "scorer")
    out = tmp_path / "run"

    eval_calls = []
    def fake_eval(tasks, **kwargs):
        eval_calls.append(tasks)
        log_path = out / "evals" / f"mock-{len(eval_calls)}.eval"
        log_path.parent.mkdir(exist_ok=True)
        log_path.write_bytes(b"eval")
        sample = tasks[0].dataset[0]
        score = SimpleNamespace(value="I", metadata={})
        returned = SimpleNamespace(id=sample.id, scores={"score": score}, messages=[],
                                   model_usage={}, limit=None, error=None, metadata=sample.metadata)
        return [SimpleNamespace(location=str(log_path), status="success", samples=[returned])]

    monkeypatch.setattr(inspect_ai, "eval", fake_eval)
    assert runner.main(["--manifest", str(plan), "--validation-audit", str(audit),
                        "--out", str(out), "--execute"]) == 0
    run_manifest = json.loads((out / "run-manifest.json").read_text())
    assert run_manifest["phase"] == "validation"
    assert run_manifest["development_assignments_executed"] is False
    assert run_manifest["communication_holdout_assignments_executed"] is False
    assert json.loads((out / "status.json").read_text())["status"] == "completed"
    from messageboardbench.confirmation import verify_completed_prompt_d_validation
    evidence = verify_completed_prompt_d_validation(plan, out)
    assert evidence["completed_assignments"] == len(manifest["validation_assignments"])
    with pytest.raises(ValueError, match="already consumed"):
        runner.consume_once(manifest, plan, tmp_path / "other")
