from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from inspect_ai.dataset import Sample

from messageboardbench.calibration_run import (
    canonical_manifest_sha256,
    prepare_development_samples,
    read_frozen_manifest,
)
from messageboardbench.prompt_calibration import (
    DEFAULT_PARTITIONS,
    TaskPartitions,
    build_manifest,
    render_tools_instruction,
)


REVISION = "c" * 40


def write_manifest(path: Path, manifest: dict) -> Path:
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


def test_reads_exact_self_hashed_immutable_manifest(tmp_path):
    manifest = build_manifest(dataset_revision=REVISION)
    path = write_manifest(tmp_path / "plan.json", manifest)
    loaded, source = read_frozen_manifest(path)
    assert loaded == manifest
    assert source["manifest_sha256"] == canonical_manifest_sha256(manifest)
    assert source["file_sha256"]

    tampered = deepcopy(manifest)
    tampered["environment"]["temperature"] = 0
    write_manifest(tmp_path / "tampered.json", tampered)
    with pytest.raises(ValueError, match="self-hash mismatch"):
        read_frozen_manifest(tmp_path / "tampered.json")

    mutable = deepcopy(manifest)
    mutable["benchmark"]["dataset_revision"] = "main"
    mutable["manifest_sha256"] = canonical_manifest_sha256(mutable)
    write_manifest(tmp_path / "mutable.json", mutable)
    with pytest.raises(ValueError, match="40-character"):
        read_frozen_manifest(tmp_path / "mutable.json")


def test_rejects_default_communication_holdout_even_if_redeclared(tmp_path):
    partitions = TaskPartitions(
        development=(DEFAULT_PARTITIONS.communication_holdout[0],),
        validation=("validation-x",),
        communication_holdout=("holdout-x",),
    )
    manifest = build_manifest(dataset_revision=REVISION, partitions=partitions)
    path = write_manifest(tmp_path / "bad-plan.json", manifest)
    with pytest.raises(ValueError, match="communication holdout"):
        read_frozen_manifest(path)


def test_manifest_binds_generation_and_retry_settings(tmp_path):
    manifest = build_manifest(dataset_revision=REVISION)
    environment = manifest["environment"]
    assert environment["temperature"] == 1
    assert environment["reasoning_effort"] == "high"
    assert environment["strict_tools"] is False
    assert environment["sample_retries"] == 0
    assert environment["request_retries"] == 1
    assert environment["assignment_concurrency"] == 1

    for field, value in (
        ("strict_tools", True),
        ("sample_retries", 1),
        ("request_retries", 2),
        ("assignment_concurrency", 2),
    ):
        changed = deepcopy(manifest)
        changed["environment"][field] = value
        changed["manifest_sha256"] = canonical_manifest_sha256(changed)
        path = write_manifest(tmp_path / f"bad-{field}.json", changed)
        with pytest.raises(ValueError, match=field):
            read_frozen_manifest(path)


def test_prepared_samples_preserve_prompt_provenance_and_never_load_holdout():
    partitions = TaskPartitions(
        development=("dev-1",), validation=("val-1",), communication_holdout=("hold-1",)
    )
    manifest = build_manifest(dataset_revision=REVISION, partitions=partitions)
    calls = []

    def loader(revision):
        calls.append(revision)
        base = render_tools_instruction("A")
        return {
            split: {
                "dev-1": Sample(
                    id="dev-1",
                    input=base,
                    metadata={
                        "instruction_prompt": base,
                        "prompt": "def candidate(x):",
                        "test": "def check(candidate): pass",
                        "entry_point": "candidate",
                        "impossible_type": split,
                    },
                )
            }
            for split in ("original", "conflicting")
        }

    source = {"path": "/plan.json", "file_sha256": "f" * 64,
              "manifest_sha256": manifest["manifest_sha256"]}
    prepared = prepare_development_samples(manifest, source, loader=loader)
    assert calls == [REVISION]
    assert len(prepared) == 8
    assert {row["assignment"]["task_id"] for row in prepared} == {"dev-1"}
    for row in prepared:
        metadata = row["sample"].metadata
        provenance = metadata["calibration"]
        assert provenance["communication"] == "none"
        assert provenance["manifest"] == source
        assert provenance["completion"] == metadata["completion"]
        assert provenance["policy_prompt"]["rendered_instruction_prompt"] == row["sample"].input
        assert provenance["task_prompt_sha256"]
        assert provenance["test_sha256"]


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "run_prompt_calibration", Path(__file__).parents[1] / "scripts/run_prompt_calibration.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runner_preview_does_not_load_dataset_create_output_or_execute(tmp_path, monkeypatch, capsys):
    runner = load_runner()
    plan = write_manifest(tmp_path / "plan.json", build_manifest(dataset_revision=REVISION))
    out = tmp_path / "run"
    monkeypatch.setattr(
        runner,
        "prepare_development_samples",
        lambda *args, **kwargs: pytest.fail("preview must not load the dataset"),
    )
    assert runner.main(["--manifest", str(plan), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert '"execute": false' in printed
    assert "Preview only" in printed
    assert not out.exists()


def test_execute_requires_remote_docker_wrapper_before_loading_dataset(tmp_path, monkeypatch):
    runner = load_runner()
    plan = write_manifest(tmp_path / "plan.json", build_manifest(dataset_revision=REVISION))
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(
        runner,
        "prepare_development_samples",
        lambda *args, **kwargs: pytest.fail("wrong Docker host must fail before dataset loading"),
    )
    with pytest.raises(RuntimeError, match="remote Docker daemon"):
        runner.main([
            "--manifest", str(plan), "--out", str(tmp_path / "run"), "--execute"
        ])


def test_resume_requires_execute(tmp_path):
    runner = load_runner()
    plan = write_manifest(tmp_path / "plan.json", build_manifest(dataset_revision=REVISION))
    with pytest.raises(SystemExit):
        runner.main([
            "--manifest", str(plan), "--out", str(tmp_path / "run"), "--resume"
        ])


def test_resume_refuses_an_in_flight_assignment(tmp_path, monkeypatch):
    runner = load_runner()
    manifest = build_manifest(dataset_revision=REVISION)
    plan = write_manifest(tmp_path / "plan.json", manifest)
    _, source = read_frozen_manifest(plan)
    out = tmp_path / "run"
    out.mkdir()
    (out / "frozen-plan.json").write_bytes(plan.read_bytes())
    (out / "run-manifest.json").write_text(json.dumps({"manifest": source}))
    (out / "status.json").write_text(json.dumps({
        "status": "interrupted", "phase": "development",
        "completed_assignments": 0, "in_flight_assignment": 1,
    }))
    (out / "budget-before.json").write_text(json.dumps({"usage": 0.0}))
    monkeypatch.setattr(runner, "prepare_development_samples",
                        lambda *args: [None] * len(manifest["development_assignments"]))
    monkeypatch.setattr(runner, "budget", lambda: {
        "usage": 0.0, "limit": 5.0, "limit_remaining": 5.0
    })
    monkeypatch.setenv("DOCKER_HOST", runner.REMOTE_DOCKER_HOST)
    with pytest.raises(ValueError, match="implicit sample retry"):
        runner.main([
            "--manifest", str(plan), "--out", str(out), "--execute", "--resume"
        ])


def test_mock_execution_uses_only_frozen_settings_and_preserves_results(
    tmp_path, monkeypatch
):
    runner = load_runner()
    manifest = build_manifest(dataset_revision=REVISION, temperature=0.4,
                              reasoning_effort="low")
    assignment = manifest["development_assignments"][0]
    manifest["development_assignments"] = [assignment]
    plan = write_manifest(tmp_path / "plan.json", manifest)
    source = {"path": str(plan.resolve()), "file_sha256": "e" * 64,
              "manifest_sha256": manifest["manifest_sha256"]}
    monkeypatch.setattr(runner, "read_frozen_manifest", lambda path: (manifest, source))
    base = render_tools_instruction(assignment["prompt_variant"])
    sample = Sample(
        id=assignment["task_id"], input=base,
        metadata={
            "instruction_prompt": base,
            "prompt": "def candidate(x):",
            "test": "def check(candidate): pass",
            "entry_point": "candidate",
            "calibration": {"communication": "none", "completion":
                            manifest["environment"]["completion_policy"]},
            "completion": manifest["environment"]["completion_policy"],
        },
    )
    monkeypatch.setattr(runner, "prepare_development_samples", lambda *args: [{
        "assignment": assignment, "sample": sample, "provenance": sample.metadata["calibration"]
    }])
    budget_values = iter([
        {"usage": 1.0, "limit": 5.0, "limit_remaining": 4.0},
        {"usage": 1.1, "limit": 5.0, "limit_remaining": 3.9},
    ])
    monkeypatch.setattr(runner, "budget", lambda: next(budget_values))
    monkeypatch.setenv("DOCKER_HOST", runner.REMOTE_DOCKER_HOST)

    import inspect_ai
    import messageboardbench.board_task as board_task
    import messageboardbench.task as task_module
    monkeypatch.setattr(inspect_ai, "Task", lambda **kwargs: SimpleNamespace(**kwargs))
    solver_calls = []
    monkeypatch.setattr(
        board_task, "episode_solver",
        lambda *args, **kwargs: solver_calls.append((args, kwargs)) or "private-solver",
    )
    monkeypatch.setattr(task_module, "scratch_scorer", lambda split: f"scorer-{split}")
    calls = []

    def fake_eval(tasks, **kwargs):
        calls.append((tasks, kwargs))
        score = SimpleNamespace(value="C", metadata={"scratch_files": {},
                                                       "test_modified_ever": False})
        returned = SimpleNamespace(
            id=sample.id, scores={"score": score}, messages=[], model_usage={},
            limit=None, error=None, metadata=sample.metadata,
        )
        return [SimpleNamespace(location="mock.eval", status="success", samples=[returned])]

    monkeypatch.setattr(inspect_ai, "eval", fake_eval)
    out = tmp_path / "run"
    assert runner.main([
        "--manifest", str(plan), "--out", str(out), "--execute"
    ]) == 0
    assert len(calls) == 1
    task, kwargs = calls[0][0][0], calls[0][1]
    assert task.solver == "private-solver"
    assert solver_calls[0][1] == {"completion_mode": "plain-final"}
    assert kwargs["temperature"] == 0.4
    assert kwargs["reasoning_effort"] == "low"
    assert kwargs["model_args"] == {"strict_tools": False}
    assert kwargs["retry_on_error"] == 0 and kwargs["max_retries"] == 1
    result = json.loads((out / "results.json").read_text())[0]
    assert result["assignment"] == assignment
    assert result["calibration"]["communication"] == "none"
    assert result["completion"] == manifest["environment"]["completion_policy"]
    status = json.loads((out / "status.json").read_text())
    assert status["status"] == "completed"
    assert status["in_flight_assignment"] is None
