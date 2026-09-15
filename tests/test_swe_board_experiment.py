import hashlib
import json

import pytest

from scripts.swe_board_experiment import sentinel_failed, validate_resume_sources


def row(task: str, *, score=0.0, error=None, log_status="success") -> dict:
    return {
        "team": 4,
        "condition": "board",
        "sample_id": task,
        "score": score,
        "error": error,
        "log_status": log_status,
        "model_patch_captured": True,
    }


def test_sentinel_accepts_complete_valid_terminal_outcomes_including_nonpass():
    assert not sentinel_failed(
        [row("a"), row("b", score=1.0)],
        team=4,
        condition="board",
        instance_ids=["a", "b"],
    )


def test_sentinel_failure_is_sticky_for_resume():
    assert sentinel_failed(
        [row("a"), row("b", score=None, error="container failed", log_status="error")],
        team=4,
        condition="board",
        instance_ids=["a", "b"],
    )
    assert sentinel_failed(
        [row("a")], team=4, condition="board", instance_ids=["a", "b"]
    )


def test_resume_rejects_current_source_changed_after_snapshot(tmp_path):
    source = tmp_path / "runner.py"
    source.write_text("frozen\n")
    archive = tmp_path / "snapshot"
    archive.mkdir()
    archived = archive / "0-runner.py"
    archived.write_bytes(source.read_bytes())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    (archive / "index.json").write_text(json.dumps([{
        "source": str(source.resolve()), "archived": archived.name, "sha256": digest,
    }]))
    validate_resume_sources(archive, [source])
    source.write_text("changed\n")
    with pytest.raises(RuntimeError, match="current behavioral source"):
        validate_resume_sources(archive, [source])
