from pathlib import Path
import errno
import os

import pytest

from messageboardbench.shared import (
    TEAM_COMPOSE, prepare_team_directory, snapshot_team_directory,
    validate_team_directory, render_team_compose,
)


def test_creates_shared_board_and_dedicated_agent_folders(tmp_path):
    team = prepare_team_directory(tmp_path, "team-1", ["agent-1", "agent-2"])
    assert team == tmp_path / "shared" / "team-1"
    assert (team / "board").is_dir()
    assert (team / "agents" / "agent-2").is_dir()
    with pytest.raises(FileExistsError):
        prepare_team_directory(tmp_path, "team-1", ["agent-1"])


@pytest.mark.parametrize("name", ["../outside", "/workspace", "a/b", "a b", "", "."])
def test_rejects_unsafe_team_names(tmp_path, name):
    with pytest.raises(ValueError):
        prepare_team_directory(tmp_path, name, ["agent-1"])


def test_rejects_mount_of_run_root_and_shared_symlink(tmp_path):
    with pytest.raises(ValueError):
        validate_team_directory(tmp_path, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "shared").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        prepare_team_directory(tmp_path, "team-1", ["agent-1"])


def test_snapshot_skips_links_to_logs_and_handles_binary_and_large_files(tmp_path):
    team = prepare_team_directory(tmp_path, "team-1", ["agent-1"])
    secret = tmp_path / "researcher-log.txt"
    secret.write_text("private provenance")
    (team / "board" / "log-link").symlink_to(secret)
    (team / "board" / "directory-link").symlink_to(tmp_path, target_is_directory=True)
    (team / "board" / "note").write_bytes(b"abcdef\xff")
    snapshot = snapshot_team_directory(team, max_bytes=4)
    assert snapshot["board/log-link"] == {"kind": "symlink", "skipped": True}
    assert snapshot["board/directory-link"]["skipped"]
    assert snapshot["board/note"]["content"] == "abcd"
    assert snapshot["board/note"]["truncated"]
    assert "private provenance" not in str(snapshot)


def test_snapshot_limit_and_missing_root_are_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        snapshot_team_directory(tmp_path / "absent")
    team = prepare_team_directory(tmp_path, "team-1", ["agent-1"])
    with pytest.raises(ValueError, match="entry limit"):
        snapshot_team_directory(team, max_files=1)


def test_production_compose_mount_is_explicit_and_local_workdir_unshared():
    import yaml
    config = yaml.safe_load(TEAM_COMPOSE.read_text())
    service = config["services"]["default"]
    assert service["working_dir"] == "/workspace"
    assert service["network_mode"] == "none"
    assert len(service["volumes"]) == 1
    mount = service["volumes"][0]
    assert mount["target"] == "/workspace/scratch"
    assert "SAMPLE_METADATA_TEAM_DIR" in mount["source"]
    assert mount["bind"]["create_host_path"] is False


def test_installed_inspect_resolves_team_metadata_for_production_compose(tmp_path):
    from inspect_ai.util._sandbox.docker.docker import resolve_config_environment

    team = prepare_team_directory(tmp_path, "team-1", ["agent-1"])
    resolved = resolve_config_environment(str(TEAM_COMPOSE), {"team_dir": str(team)})
    assert resolved is not None
    assert resolved.env["SAMPLE_METADATA_TEAM_DIR"] == str(team)


def test_snapshot_records_file_deleted_between_listing_and_stat(tmp_path, monkeypatch):
    team = prepare_team_directory(tmp_path, "team-1", ["agent-1"])
    (team / "board" / "temporary").write_text("draft")
    original_stat = os.stat

    def disappearing_stat(path, *args, **kwargs):
        if path == "temporary" and "dir_fd" in kwargs:
            raise FileNotFoundError(errno.ENOENT, "concurrently renamed", path)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", disappearing_stat)
    snapshot = snapshot_team_directory(team)
    assert snapshot["board/temporary"]["kind"] == "transient"
    assert snapshot["board/temporary"]["errno"] == errno.ENOENT


def test_snapshot_records_symlink_substituted_between_stat_and_open(tmp_path, monkeypatch):
    team = prepare_team_directory(tmp_path, "team-1", ["agent-1"])
    note = team / "board" / "note"
    note.write_text("draft")
    secret = tmp_path / "private-log"
    secret.write_text("private provenance")
    original_open = os.open

    def replaced_open(path, flags, *args, **kwargs):
        if path == "note" and "dir_fd" in kwargs:
            note.unlink()
            note.symlink_to(secret)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replaced_open)
    snapshot = snapshot_team_directory(team)
    assert snapshot["board/note"]["kind"] == "transient"
    assert "private provenance" not in str(snapshot)


def test_rendered_compose_needs_no_sample_metadata_at_task_initialization(tmp_path):
    import json
    from inspect_ai.util._sandbox.docker.docker import resolve_config_environment

    team = prepare_team_directory(tmp_path, "team-1", ["agent-1"])
    path = render_team_compose(team, tmp_path / "config" / "team.compose.json")
    assert "${" not in path.read_text()
    config = json.loads(path.read_text())
    assert config["services"]["default"]["volumes"][0]["source"] == str(team)
    assert resolve_config_environment(str(path), {}).env == {}
    assert render_team_compose(team, path) == path
    other = prepare_team_directory(tmp_path, "team-2", ["agent-1"])
    with pytest.raises(ValueError, match="differs"):
        render_team_compose(other, path)


def test_rendered_compose_cannot_be_written_into_agent_mount(tmp_path):
    team = prepare_team_directory(tmp_path, "team-1", ["agent-1"])
    with pytest.raises(ValueError, match="outside"):
        render_team_compose(team, team / "compose.json")
