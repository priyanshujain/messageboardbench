"""Fail-closed, no-model validation for a paired ImpossibleBench SWE instance."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


DATASET = "fjzzq2002/impossible_swebench"
REMOTE_DOCKER_HOST = "ssh://pj@100.68.126.75"
FULL_SHA = re.compile(r"[0-9a-f]{40}\Z")
PATCH_PATH_RE = re.compile(r"^(?:--- a/|\+\+\+ b/)(.+)$", re.MULTILINE)


class ValidationError(RuntimeError):
    """An infrastructure or prerequisite check failed."""


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def require_revision(revision: str) -> str:
    if not FULL_SHA.fullmatch(revision):
        raise ValueError("dataset revision must be a full 40-character lowercase commit SHA")
    return revision


def normalize_record(record: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    for key in ("FAIL_TO_PASS", "PASS_TO_PASS"):
        if isinstance(normalized.get(key), str):
            normalized[key] = json.loads(normalized[key])
    return normalized


def validate_pair(original: Mapping[str, Any], conflicting: Mapping[str, Any]) -> None:
    """Check pair identity and patch lineage without claiming semantic impossibility."""
    original = normalize_record(original)
    conflicting = normalize_record(conflicting)
    identity = ("instance_id", "repo", "version", "base_commit", "patch")
    mismatches = [key for key in identity if original.get(key) != conflicting.get(key)]
    if mismatches:
        raise ValidationError(f"split pair differs in identity fields: {mismatches}")
    if original.get("test_patch") != original.get("original_test_patch"):
        raise ValidationError("original split test_patch does not equal original_test_patch")
    if conflicting.get("original_test_patch") != original.get("test_patch"):
        raise ValidationError("conflicting split does not preserve the original test patch")
    if conflicting.get("test_patch") == original.get("test_patch"):
        raise ValidationError("conflicting and original test patches are identical")
    for label, record in (("original", original), ("conflicting", conflicting)):
        for key in ("FAIL_TO_PASS", "PASS_TO_PASS"):
            if not isinstance(record.get(key), list):
                raise ValidationError(f"{label} {key} is not a parsed list")


def load_pair(revision: str, instance_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load exactly one matching record from each split at an immutable revision."""
    require_revision(revision)
    from datasets import load_dataset

    records: dict[str, dict[str, Any]] = {}
    for split in ("original", "conflicting"):
        dataset = load_dataset(DATASET, split=split, revision=revision)
        matches = [row for row in dataset if row["instance_id"] == instance_id]
        if len(matches) != 1:
            raise ValidationError(
                f"expected exactly one {split} record for {instance_id!r}; found {len(matches)}"
            )
        records[split] = normalize_record(matches[0])
    validate_pair(records["original"], records["conflicting"])
    return records["original"], records["conflicting"]


def swebench_spec(record: Mapping[str, Any]) -> tuple[str, list[str], str]:
    """Resolve image, test directives and command using the pinned SWE-bench API."""
    try:
        from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS
        from swebench.harness.test_spec.python import get_test_directives
        from swebench.harness.test_spec.test_spec import make_test_spec
    except ImportError as exc:
        raise ValidationError(
            "SWE dependencies are absent; run `just swe-install`"
        ) from exc

    spec = make_test_spec(dict(record), namespace="swebench")
    image = spec.instance_image_key
    if ".x86_64." not in image:
        raise ValidationError(f"resolved non-x86_64 SWE image: {image}")
    directives = list(get_test_directives(dict(record)))
    if not directives:
        raise ValidationError("SWE-bench resolved no test directives")
    try:
        test_command = MAP_REPO_VERSION_TO_SPECS[record["repo"]][record["version"]][
            "test_cmd"
        ]
    except KeyError as exc:
        raise ValidationError("SWE-bench has no test command for repo/version") from exc
    return image, directives, str(test_command)


def patch_files(patch: str) -> list[str]:
    paths = sorted(set(PATCH_PATH_RE.findall(patch)))
    unsafe = any(
        path == "/dev/null"
        or path.startswith("/")
        or ".." in Path(path).parts
        or any(ord(character) < 32 for character in path)
        for path in paths
    )
    if not paths or unsafe:
        raise ValidationError("test patch did not resolve to safe repository-relative files")
    return paths


def parse_target_statuses(record: Mapping[str, Any], output: str) -> dict[str, str]:
    """Parse target tests through SWE-bench's repo-specific parser."""
    from swebench.harness.grading import MAP_REPO_TO_PARSER

    parser = MAP_REPO_TO_PARSER[record["repo"]]
    try:
        parsed = parser(output)
    except TypeError:
        from swebench.harness.test_spec.test_spec import make_test_spec

        parsed = parser(output, make_test_spec(dict(record)))
    targets = [*record["FAIL_TO_PASS"], *record["PASS_TO_PASS"]]
    return {target: parsed.get(target, "MISSING") for target in targets}


@dataclass(frozen=True)
class TrialResult:
    split: str
    mode: str
    exit_code: int
    output_file: str
    output_sha256: str
    image: str
    image_id: str
    repo_digests: list[str]
    test_command: list[str]
    target_statuses: dict[str, str]
    resolved: bool


Runner = Callable[..., subprocess.CompletedProcess[str]]


def docker_preflight(environ: Mapping[str, str], run: Runner = subprocess.run) -> None:
    if environ.get("DOCKER_HOST") != REMOTE_DOCKER_HOST:
        raise ValidationError(
            f"DOCKER_HOST must be exactly {REMOTE_DOCKER_HOST}; use `just swe-validate ...`"
        )
    result = run(
        ["docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"],
        capture_output=True,
        text=True,
        timeout=30,
        env=dict(environ),
    )
    if result.returncode != 0 or result.stdout.strip() != "linux/amd64":
        raise ValidationError(
            f"remote Docker preflight failed: rc={result.returncode}, server={result.stdout.strip()!r}"
        )


def image_identity(
    image: str, environ: Mapping[str, str], run: Runner = subprocess.run
) -> tuple[str, list[str]]:
    result = _docker(
        ["image", "inspect", image, "--format", "{{json .}}"], environ, run,
        capture_output=True,
    )
    _must(result, "image inspection")
    try:
        value = json.loads(result.stdout)
        image_id = value["Id"]
        repo_digests = sorted(value["RepoDigests"] or [])
        platform = f"{value['Os']}/{value['Architecture']}"
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValidationError("Docker returned an invalid image identity") from exc
    if platform != "linux/amd64" or not image_id or not repo_digests:
        raise ValidationError(
            f"image must be linux/amd64 with an ID and repository digest; got {platform}, "
            f"id={image_id!r}, digests={repo_digests!r}"
        )
    return image_id, repo_digests


def _docker(
    args: Sequence[str], environ: Mapping[str, str], run: Runner = subprocess.run, **kwargs: Any
) -> subprocess.CompletedProcess[str]:
    return run(["docker", *args], env=dict(environ), text=True, **kwargs)


def _must(result: subprocess.CompletedProcess[str], action: str) -> None:
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise ValidationError(f"{action} failed (exit {result.returncode}): {detail}")


def run_trial(
    record: Mapping[str, Any],
    *,
    split: str,
    mode: str,
    out_dir: Path,
    environ: Mapping[str, str],
    run: Runner = subprocess.run,
    memory: str = "8g",
    timeout_seconds: int = 600,
) -> TrialResult:
    """Run nochange or oracle in a fresh, network-disabled remote container."""
    if split not in {"original", "conflicting"} or mode not in {"nochange", "oracle"}:
        raise ValueError("split/mode must be original|conflicting and nochange|oracle")
    image, directives, test_command = swebench_spec(record)
    image_id, repo_digests = image_identity(image, environ, run)
    patch_files(str(record["test_patch"]))
    container = "mbb-swe-" + uuid.uuid4().hex[:12]
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"{split}-{mode}.txt"

    started = _docker(
        [
            "run", "--detach", "--rm", "--name", container, "--network", "none",
            "--memory", memory, "--workdir", "/testbed", image, "sleep", "infinity",
        ],
        environ,
        run,
        capture_output=True,
    )
    _must(started, "container start")
    try:
        base = str(record["base_commit"])
        reset = _docker(
            ["exec", container, "git", "reset", "--hard", base], environ, run,
            capture_output=True,
        )
        _must(reset, "base reset")
        cleaned = _docker(
            ["exec", container, "git", "clean", "-fd"], environ, run,
            capture_output=True,
        )
        _must(cleaned, "repository clean")

        with tempfile.TemporaryDirectory(prefix="mbb-swe-") as tmp:
            temp = Path(tmp)
            test_patch = temp / "test.patch"
            test_patch.write_text(str(record["test_patch"]))
            copied = _docker(
                ["cp", str(test_patch), f"{container}:/tmp/test.patch"], environ, run,
                capture_output=True,
            )
            _must(copied, "test-patch copy")
            checked = _docker(
                ["exec", container, "git", "apply", "--check", "/tmp/test.patch"],
                environ, run, capture_output=True,
            )
            _must(checked, "test-patch check")
            applied = _docker(
                ["exec", container, "git", "apply", "/tmp/test.patch"], environ, run,
                capture_output=True,
            )
            _must(applied, "test-patch apply")
            if mode == "oracle":
                oracle_patch = temp / "oracle.patch"
                oracle_patch.write_text(str(record["patch"]))
                copied = _docker(
                    ["cp", str(oracle_patch), f"{container}:/tmp/oracle.patch"], environ,
                    run, capture_output=True,
                )
                _must(copied, "oracle-patch copy")
                checked = _docker(
                    ["exec", container, "git", "apply", "--check", "/tmp/oracle.patch"],
                    environ, run, capture_output=True,
                )
                _must(checked, "oracle-patch check")
                applied = _docker(
                    ["exec", container, "git", "apply", "/tmp/oracle.patch"], environ,
                    run, capture_output=True,
                )
                _must(applied, "oracle-patch apply")

        command = [*shlex.split(test_command), *directives]
        shell_command = " ".join(shlex.quote(part) for part in command)
        tested = _docker(
            [
                "exec", container, "bash", "-lc",
                "source /opt/miniconda3/bin/activate && conda activate testbed && "
                + shell_command,
            ],
            environ,
            run,
            capture_output=True,
            timeout=timeout_seconds,
        )
        combined = tested.stdout + ("\n[stderr]\n" + tested.stderr if tested.stderr else "")
        output_path.write_text(combined)
        statuses = parse_target_statuses(record, combined)
        accepted = {"PASSED", "XFAIL"}
        resolved = tested.returncode == 0 and all(
            status in accepted for status in statuses.values()
        )
        return TrialResult(
            split=split,
            mode=mode,
            exit_code=tested.returncode,
            output_file=output_path.name,
            output_sha256=sha256_text(combined),
            image=image,
            image_id=image_id,
            repo_digests=repo_digests,
            test_command=command,
            target_statuses=statuses,
            resolved=resolved,
        )
    finally:
        _docker(["rm", "--force", container], environ, run, capture_output=True)


def validate_expected_matrix(results: Sequence[TrialResult]) -> None:
    observed = {(r.split, r.mode): r for r in results}
    expected = {
        ("original", "nochange"): False,
        ("original", "oracle"): True,
        ("conflicting", "nochange"): False,
        ("conflicting", "oracle"): False,
    }
    if set(observed) != set(expected):
        raise ValidationError("validation matrix is incomplete")
    identities = {(result.image_id, tuple(result.repo_digests)) for result in results}
    if len(identities) != 1:
        raise ValidationError("trials did not use one identical remote image ID/digest")
    mismatches = [
        f"{split}/{mode}=exit {observed[(split, mode)].exit_code},resolved={observed[(split, mode)].resolved}"
        for (split, mode), should_pass in expected.items()
        if observed[(split, mode)].resolved != should_pass
    ]
    if mismatches:
        raise ValidationError("unexpected nochange/oracle outcomes: " + ", ".join(mismatches))


def validate_semantic_audit(audit: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    """Require a human semantic review before any Docker trial starts."""
    matched = (
        "dataset", "dataset_revision", "instance_id", "original_test_patch_sha256",
        "conflicting_test_patch_sha256", "oracle_patch_sha256",
    )
    mismatches = [key for key in matched if audit.get(key) != expected.get(key)]
    if mismatches:
        raise ValidationError(f"semantic audit does not match selected pair: {mismatches}")
    required_text = ("reviewer", "reviewed_at", "contradiction_description")
    if audit.get("same_input_contradiction_reviewed") is not True or any(
        not str(audit.get(key, "")).strip() for key in required_text
    ):
        raise ValidationError(
            "semantic audit needs same_input_contradiction_reviewed=true, reviewer, "
            "reviewed_at and contradiction_description"
        )


def manifest(
    revision: str,
    instance_id: str,
    original: Mapping[str, Any],
    conflicting: Mapping[str, Any],
    results: Sequence[TrialResult] = (),
) -> dict[str, Any]:
    image, directives, command = swebench_spec(original)
    remote_image = None
    if results:
        identities = {(result.image_id, tuple(result.repo_digests)) for result in results}
        if len(identities) != 1:
            raise ValidationError("manifest cannot record divergent remote image identities")
        image_id, repo_digests = next(iter(identities))
        remote_image = {"id": image_id, "repo_digests": list(repo_digests)}
    return {
        "schema_version": 1,
        "dataset": DATASET,
        "dataset_revision": require_revision(revision),
        "instance_id": instance_id,
        "repo": original["repo"],
        "version": original["version"],
        "base_commit": original["base_commit"],
        "image": image,
        "remote_image": remote_image,
        "test_command": [*shlex.split(command), *directives],
        "network": "none",
        "original_test_patch_sha256": sha256_text(str(original["test_patch"])),
        "conflicting_test_patch_sha256": sha256_text(str(conflicting["test_patch"])),
        "oracle_patch_sha256": sha256_text(str(original["patch"])),
        "results": [asdict(result) for result in results],
    }
