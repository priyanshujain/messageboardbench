"""Fail-closed lifecycle for a frozen, unattended experiment bundle."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Callable


SCHEMA_VERSION = 1
REMOTE_DOCKER_HOST = "ssh://pj@100.68.126.75"
PYTHON = ".venv/bin/python"
REMOTE_WRAPPER = "scripts/remote_docker.py"
ALLOWED_POSTPROCESS_SCRIPTS = {
    "scripts/board_report.py",
    "scripts/analysis/validate_board_export.py",
    "scripts/analysis/board_resources.py",
    "scripts/swe_population_report.py",
    "scripts/analysis/verify_swe_population.py",
}


def canonical_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def manifest_sha256(manifest: dict[str, Any]) -> str:
    unhashed = dict(manifest)
    unhashed.pop("manifest_sha256", None)
    return canonical_sha256(unhashed)


def _resolve_local(root: Path, value: str, *, field: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError(f"{field} must be a nonempty repository-relative path")
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"{field} escapes the repository")
    return path


def _validate_argv(root: Path, argv: Any, *, postprocess: bool) -> list[str]:
    if not isinstance(argv, list) or not argv or not all(
        isinstance(item, str) and item for item in argv
    ):
        raise ValueError("command argv must be a nonempty list of strings")
    if len(argv) < 2 or argv[0] != PYTHON:
        raise ValueError(f"commands must use the repository interpreter {PYTHON}")
    script = argv[1]
    script_path = _resolve_local(root, script, field="command script")
    if not script.startswith("scripts/") or not script_path.is_file():
        raise ValueError(f"command script must be an existing file under scripts/: {script}")
    if postprocess:
        if script not in ALLOWED_POSTPROCESS_SCRIPTS:
            raise ValueError(f"postprocess script is not offline-allowlisted: {script}")
        if "--execute" in argv:
            raise ValueError("postprocess commands cannot contain --execute")
    elif "--execute" not in argv:
        raise ValueError("execution command must explicitly contain --execute")
    return argv


def validate_manifest(manifest: dict[str, Any], root: Path, *, require_ready: bool = True) -> None:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"bundle manifest must use schema_version {SCHEMA_VERSION}")
    if require_ready and manifest.get("status") != "ready":
        blockers = manifest.get("blockers") or ["design has not been frozen"]
        raise ValueError("bundle is not ready: " + "; ".join(map(str, blockers)))
    if manifest.get("status") != "ready":
        return
    if manifest.get("blockers"):
        raise ValueError("ready bundle cannot retain blockers")
    if not isinstance(manifest.get("experiment_id"), str) or not manifest["experiment_id"]:
        raise ValueError("ready bundle requires a nonempty experiment_id")
    if manifest.get("remote_docker_host") != REMOTE_DOCKER_HOST:
        raise ValueError(f"remote_docker_host must be exactly {REMOTE_DOCKER_HOST}")
    if manifest.get("manifest_sha256") != manifest_sha256(manifest):
        raise ValueError("bundle manifest self-hash mismatch")

    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("outputs must be an object")
    required_outputs = {"run_dir", "report_dir", "verification_file", "resource_file", "state_file"}
    if set(outputs) != required_outputs:
        raise ValueError(f"outputs must contain exactly {sorted(required_outputs)}")
    paths = {name: _resolve_local(root, value, field=f"outputs.{name}")
             for name, value in outputs.items()}
    if any(not value.startswith("logs/") for value in outputs.values()):
        raise ValueError("automatic run, report, verification, resource, and state outputs must be under ignored logs/")
    if any(paths[a] == paths[b] for a in paths for b in paths if a != b):
        raise ValueError("output paths must be distinct")
    execution = manifest.get("execution")
    resumable = isinstance(execution, dict) and execution.get("resume") is True
    for name in ("run_dir", "report_dir", "verification_file", "resource_file", "state_file"):
        if paths[name].exists() and not resumable:
            raise ValueError(f"fresh output already exists: {outputs[name]}")

    if not isinstance(execution, dict) or set(execution) not in ({"argv"}, {"argv", "resume"}):
        raise ValueError("execution must contain argv and optional resume=true")
    if "resume" in execution and execution["resume"] is not True:
        raise ValueError("execution.resume may only be true")
    execution_argv = _validate_argv(root, execution["argv"], postprocess=False)
    try:
        out_index = execution_argv.index("--out")
        configured_out = execution_argv[out_index + 1]
    except (ValueError, IndexError) as exc:
        raise ValueError("execution argv must include --out RUN_DIR") from exc
    if configured_out != outputs["run_dir"]:
        raise ValueError("execution --out must equal outputs.run_dir")

    steps = manifest.get("postprocess")
    if not isinstance(steps, list) or not steps:
        raise ValueError("postprocess must contain at least one offline step")
    names: set[str] = set()
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or set(step) != {"name", "requires", "argv"}:
            raise ValueError(f"postprocess[{index}] must contain name, requires, and argv")
        name = step["name"]
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("postprocess names must be nonempty and unique")
        names.add(name)
        requires = step["requires"]
        if not isinstance(requires, list) or not all(isinstance(item, str) and item for item in requires):
            raise ValueError(f"postprocess[{index}].requires must be a list of paths")
        for value in requires:
            _resolve_local(root, value, field=f"postprocess[{index}].requires")
        argv = _validate_argv(root, step["argv"], postprocess=True)
        bound_output = {
            "report": outputs["report_dir"],
            "verify": outputs["verification_file"],
            "resources": outputs["resource_file"],
        }.get(name)
        if bound_output is None or bound_output not in argv:
            raise ValueError(f"postprocess step {name!r} is not bound to its configured output")
    if names != {"report", "verify", "resources"}:
        raise ValueError("postprocess must contain exactly report, verify, and resources steps")


def load_and_validate(path: Path, root: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    manifest = json.loads(raw)
    validate_manifest(manifest, root)
    return manifest, raw


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_status(path: Path, status: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(status, indent=2) + "\n")
    temporary.replace(path)


def _claim_status(path: Path, status: dict[str, Any]) -> None:
    """Atomically consume a fresh bundle so two starts cannot launch it twice."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(status, handle, indent=2)
        handle.write("\n")


def run_bundle(
    manifest_path: Path,
    root: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    """Run once, then attempt each safe offline step whose inputs exist."""
    manifest, raw = load_and_validate(manifest_path, root)
    outputs = manifest["outputs"]
    state_path = _resolve_local(root, outputs["state_file"], field="outputs.state_file")
    if manifest["execution"].get("resume") is True and state_path.exists():
        previous = json.loads(state_path.read_text())
        attempt = int(previous.get("resume_count", 0)) + 1
        history = _resolve_local(root, outputs["run_dir"], field="outputs.run_dir").parent / "resume-history" / f"attempt-{attempt}"
        history.mkdir(parents=True, exist_ok=False)
        for name in ("report_dir", "verification_file", "resource_file"):
            existing = _resolve_local(root, outputs[name], field=f"outputs.{name}")
            if existing.exists():
                existing.replace(history / existing.name)
    execution_argv = list(manifest["execution"]["argv"])
    wrapped_argv = [PYTHON, REMOTE_WRAPPER, "--", *execution_argv]
    status: dict[str, Any] = {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "status": "running",
        "started_at": _utc_now(),
        "finished_at": None,
        "manifest_path": str(manifest_path.resolve()),
        "manifest_file_sha256": hashlib.sha256(raw).hexdigest(),
        "manifest_sha256": manifest["manifest_sha256"],
        "repository_root": str(root.resolve()),
        "remote_docker_host": REMOTE_DOCKER_HOST,
        "execution": {"argv": wrapped_argv, "returncode": None},
        "postprocess": [],
    }
    if state_path.exists() and manifest["execution"].get("resume") is True:
        previous = json.loads(state_path.read_text())
        if previous.get("experiment_id") != manifest["experiment_id"]:
            raise ValueError("resume state belongs to another experiment")
        status["original_started_at"] = previous.get("original_started_at", previous.get("started_at"))
        status["resume_count"] = int(previous.get("resume_count", 0)) + 1
        _write_status(state_path, status)
    else:
        _claim_status(state_path, status)

    try:
        execution_result = run(wrapped_argv, cwd=root, check=False)
        execution_rc = execution_result.returncode
    except KeyboardInterrupt:
        execution_rc = 130
    except OSError as exc:
        status["execution"]["error"] = str(exc)
        execution_rc = 127
    status["execution"]["returncode"] = execution_rc
    _write_status(state_path, status)

    postprocess_failed = False
    for step in manifest["postprocess"]:
        missing = [value for value in step["requires"]
                   if not _resolve_local(root, value, field="postprocess.requires").exists()]
        record: dict[str, Any] = {
            "name": step["name"], "argv": step["argv"], "started_at": _utc_now()
        }
        if missing:
            record.update(status="skipped", missing_requirements=missing, finished_at=_utc_now())
        else:
            try:
                result = run(step["argv"], cwd=root, check=False)
                record.update(status="completed" if result.returncode == 0 else "failed",
                              returncode=result.returncode, finished_at=_utc_now())
                postprocess_failed |= result.returncode != 0
            except (OSError, KeyboardInterrupt) as exc:
                record.update(status="failed", returncode=130 if isinstance(exc, KeyboardInterrupt) else 127,
                              error=str(exc), finished_at=_utc_now())
                postprocess_failed = True
        status["postprocess"].append(record)
        _write_status(state_path, status)

    skipped = any(step["status"] == "skipped" for step in status["postprocess"])
    status["status"] = (
        "completed" if execution_rc == 0 and not postprocess_failed and not skipped
        else "partial" if status["postprocess"] and not postprocess_failed
        else "failed"
    )
    status["finished_at"] = _utc_now()
    _write_status(state_path, status)
    return execution_rc or (1 if postprocess_failed or skipped else 0)
