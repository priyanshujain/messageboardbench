from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

from messageboardbench import swe_validation as module


def record(**changes):
    value = {
        "instance_id": "owner__repo-1",
        "repo": "owner/repo",
        "version": "1.0",
        "base_commit": "a" * 40,
        "patch": "oracle",
        "test_patch": "--- a/tests/test_x.py\n+++ b/tests/test_x.py\n",
        "original_test_patch": "--- a/tests/test_x.py\n+++ b/tests/test_x.py\n",
        "FAIL_TO_PASS": ["tests/test_x.py::test_bug"],
        "PASS_TO_PASS": ["tests/test_x.py::test_old"],
    }
    value.update(changes)
    return value


def result(split: str, mode: str, *, resolved: bool, exit_code: int):
    return module.TrialResult(
        split=split,
        mode=mode,
        exit_code=exit_code,
        output_file=f"{split}-{mode}.txt",
        output_sha256="0" * 64,
        image="swebench/sweb.eval.x86_64.example:latest",
        image_id="sha256:abc",
        repo_digests=["swebench/example@sha256:def"],
        test_command=["pytest", "tests/test_x.py"],
        target_statuses={"tests/test_x.py::test_bug": "PASSED" if resolved else "FAILED"},
        resolved=resolved,
    )


def test_validate_pair_requires_identity_and_patch_lineage():
    original = record()
    conflicting = record(
        test_patch="--- a/tests/test_x.py\n+++ b/tests/test_x.py\n+contradiction\n"
    )
    module.validate_pair(original, conflicting)
    with pytest.raises(module.ValidationError, match="identity"):
        module.validate_pair(original, {**conflicting, "base_commit": "b" * 40})
    with pytest.raises(module.ValidationError, match="preserve"):
        module.validate_pair(
            original, {**conflicting, "original_test_patch": "different"}
        )


def test_revision_must_be_immutable_full_sha():
    assert module.require_revision("1" * 40) == "1" * 40
    for invalid in ("main", "1" * 39, "A" * 40):
        with pytest.raises(ValueError, match="40-character"):
            module.require_revision(invalid)


def test_patch_files_rejects_traversal_and_accepts_new_files():
    assert module.patch_files("--- /dev/null\n+++ b/tests/new.py\n") == ["tests/new.py"]
    with pytest.raises(module.ValidationError, match="safe"):
        module.patch_files("--- a/../secret\n+++ b/../secret\n")


def test_docker_preflight_requires_exact_remote():
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs["env"]["DOCKER_HOST"]))
        return subprocess.CompletedProcess(command, 0, "linux/amd64\n", "")

    module.docker_preflight({"DOCKER_HOST": module.REMOTE_DOCKER_HOST}, run)
    assert calls == [
        (["docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"],
         module.REMOTE_DOCKER_HOST)
    ]
    with pytest.raises(module.ValidationError, match="must be exactly"):
        module.docker_preflight({"DOCKER_HOST": "unix:///local"}, run)


def test_expected_matrix_uses_strict_resolution_not_exit_code_alone():
    good = [
        result("original", "nochange", resolved=False, exit_code=1),
        result("original", "oracle", resolved=True, exit_code=0),
        result("conflicting", "nochange", resolved=False, exit_code=1),
        result("conflicting", "oracle", resolved=False, exit_code=1),
    ]
    module.validate_expected_matrix(good)
    bad = [*good[:3], result("conflicting", "oracle", resolved=True, exit_code=0)]
    with pytest.raises(module.ValidationError, match="unexpected"):
        module.validate_expected_matrix(bad)


def test_matrix_rejects_image_identity_drift():
    values = [
        result("original", "nochange", resolved=False, exit_code=1),
        result("original", "oracle", resolved=True, exit_code=0),
        result("conflicting", "nochange", resolved=False, exit_code=1),
        result("conflicting", "oracle", resolved=False, exit_code=1),
    ]
    values[-1] = module.TrialResult(
        **{**values[-1].__dict__, "image_id": "sha256:different"}
    )
    with pytest.raises(module.ValidationError, match="identical"):
        module.validate_expected_matrix(values)


def test_image_identity_requires_digest_and_amd64():
    def run(command, **kwargs):
        payload = {
            "Id": "sha256:abc",
            "RepoDigests": ["repo@sha256:def"],
            "Os": "linux",
            "Architecture": "amd64",
        }
        return subprocess.CompletedProcess(command, 0, __import__("json").dumps(payload), "")

    assert module.image_identity("repo:tag", {"DOCKER_HOST": module.REMOTE_DOCKER_HOST}, run) == (
        "sha256:abc", ["repo@sha256:def"]
    )


def test_semantic_audit_is_bound_to_pair_hashes():
    expected = {
        "dataset": module.DATASET,
        "dataset_revision": "1" * 40,
        "instance_id": "owner__repo-1",
        "original_test_patch_sha256": "a",
        "conflicting_test_patch_sha256": "b",
        "oracle_patch_sha256": "c",
    }
    audit = {
        **expected,
        "same_input_contradiction_reviewed": True,
        "reviewer": "reviewer",
        "reviewed_at": "2026-09-09T00:00:00Z",
        "contradiction_description": "The same call is asserted to return two values.",
    }
    module.validate_semantic_audit(audit, expected)
    with pytest.raises(module.ValidationError, match="does not match"):
        module.validate_semantic_audit({**audit, "oracle_patch_sha256": "wrong"}, expected)


def test_missing_target_is_not_resolved(monkeypatch):
    constants = types.ModuleType("swebench.harness.constants")
    constants.START_TEST_OUTPUT = "START"
    constants.END_TEST_OUTPUT = "END"
    grading = types.ModuleType("swebench.harness.grading")
    grading.MAP_REPO_TO_PARSER = {
        "owner/repo": lambda output: {"tests/test_x.py::test_bug": "PASSED"}
    }
    monkeypatch.setitem(sys.modules, "swebench.harness.constants", constants)
    monkeypatch.setitem(sys.modules, "swebench.harness.grading", grading)
    statuses = module.parse_target_statuses(record(), "setup START output END cleanup")
    assert statuses == {
        "tests/test_x.py::test_bug": "PASSED",
        "tests/test_x.py::test_old": "MISSING",
    }


def test_fresh_grader_runs_exact_testspec_script_with_install_and_network_none(monkeypatch):
    from swebench.harness.constants import END_TEST_OUTPUT, START_TEST_OUTPUT

    commands = [
        "repo-install --offline", "git checkout base tests/x.py",
        "git apply evaluator", f": '{START_TEST_OUTPUT}'", "pytest tests/x.py",
        f": '{END_TEST_OUTPUT}'", "git checkout base tests/x.py",
    ]
    eval_script = "#!/bin/bash\nset -uxo pipefail\n" + "\n".join(commands) + "\n"
    monkeypatch.setattr(
        module, "swebench_test_spec", lambda value: types.SimpleNamespace(
            eval_script=eval_script, eval_script_list=commands
        )
    )
    monkeypatch.setattr(
        module, "parse_target_statuses", lambda value, output: {"target": "PASSED"}
    )
    calls = []
    copied = {}

    def run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["docker", "cp"]:
            copied[command[-1].split(":", 1)[1]] = Path(command[-2]).read_text()
        stdout = "ok"
        if command[-1] == "bash /tmp/messageboardbench-eval.sh 2>&1":
            monitored = set(range(len(commands))) - {3, 4, 5}
            stdout = "\n".join(
                f"__MBB_EVAL_COMMAND_{index:04d}__=0" for index in monitored
            ) + "\ntarget passed"
        return subprocess.CompletedProcess(command, 0, stdout, "")

    evaluated, output, statuses, script_hash, preserved_script = module.run_fresh_grader(
        record(), model_patch="diff --git a/x b/x\n", image="repo@sha256:digest",
        environ={"DOCKER_HOST": module.REMOTE_DOCKER_HOST}, run=run,
    )
    assert evaluated.returncode == 0
    assert output.endswith("target passed")
    assert statuses == {"target": "PASSED"}
    assert script_hash == module.sha256_text(eval_script)
    assert preserved_script == eval_script
    starts = [call for call in calls if call[:3] == ["docker", "run", "--detach"]]
    assert len(starts) == 1
    assert "--network" in starts[0] and starts[0][starts[0].index("--network") + 1] == "none"
    executed = copied["/tmp/messageboardbench-eval.sh"]
    assert all(command in executed for command in commands)
    assert "__MBB_EVAL_COMMAND_0000__" in executed
    assert "__MBB_EVAL_COMMAND_0004__" not in executed
    assert copied["/tmp/model.patch"] == "diff --git a/x b/x\n"
    assert calls[-1][0:3] == ["docker", "rm", "--force"]


def test_fresh_grader_rejects_non_remote_docker_before_start(monkeypatch):
    monkeypatch.setattr(
        module, "swebench_test_spec", lambda value: types.SimpleNamespace(
            eval_script="test", eval_script_list=[]
        )
    )
    with pytest.raises(module.ValidationError, match="fresh grader requires"):
        module.run_fresh_grader(
            record(), model_patch="", image="repo", environ={"DOCKER_HOST": "local"}
        )


def test_setup_install_statuses_fail_closed():
    with pytest.raises(module.ValidationError, match="indices: 2"):
        module.validate_command_statuses(
            "__MBB_EVAL_COMMAND_0001__=0\n__MBB_EVAL_COMMAND_0002__=1\n",
            {1, 2},
        )
    with pytest.raises(module.ValidationError, match="did not report every"):
        module.validate_command_statuses("__MBB_EVAL_COMMAND_0001__=0\n", {1, 2})
