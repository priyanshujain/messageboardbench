import subprocess

import pytest

import scripts.remote_docker as remote


def test_remote_host_is_default_and_mbb_override_wins():
    assert remote.docker_host({}) == "ssh://pj@100.68.126.75"
    assert remote.docker_host({"DOCKER_HOST": "unix:///local.sock"}) == remote.DEFAULT_DOCKER_HOST
    assert remote.docker_host({"MBB_DOCKER_HOST": "ssh://runner@example"}) == "ssh://runner@example"


@pytest.mark.parametrize(
    "host",
    ["unix:///var/run/docker.sock", "tcp://host:2375", "ssh://user:secret@host", "ssh://host/path"],
)
def test_non_ssh_or_sensitive_hosts_are_rejected(host):
    with pytest.raises(ValueError):
        remote.validate_host(host)


def test_check_daemon_passes_host_without_mutating_input(monkeypatch):
    seen = {}

    def run(argv, **kwargs):
        seen.update(argv=argv, kwargs=kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="linux/amd64\n", stderr="")

    monkeypatch.setattr(remote.subprocess, "run", run)
    env = {"KEEP": "yes"}
    assert remote.check_daemon("ssh://runner@host", env) == "linux/amd64"
    assert env == {"KEEP": "yes"}
    assert seen["kwargs"]["env"]["DOCKER_HOST"] == "ssh://runner@host"
    assert seen["kwargs"]["timeout"] == 30


def test_wrong_server_architecture_fails_closed(monkeypatch):
    monkeypatch.setattr(
        remote.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="linux/arm64\n"),
    )
    with pytest.raises(RuntimeError, match="expected"):
        remote.check_daemon(remote.DEFAULT_DOCKER_HOST, {})


def test_main_checks_then_runs_local_command_with_remote_environment(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(argv, 0, stdout="linux/amd64\n", stderr="")
        return subprocess.CompletedProcess(argv, 7)

    monkeypatch.setattr(remote.subprocess, "run", run)
    assert remote.main(["--", "python", "job.py"], {}) == 7
    assert calls[1][0] == ["python", "job.py"]
    assert calls[1][1]["env"]["DOCKER_HOST"] == remote.DEFAULT_DOCKER_HOST
    assert calls[1][1].get("shell", False) is False


def test_main_reports_interrupted_child_without_traceback(monkeypatch):
    calls = 0

    def run(argv, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(argv, 0, stdout="linux/amd64\n", stderr="")
        raise KeyboardInterrupt

    monkeypatch.setattr(remote.subprocess, "run", run)
    assert remote.main(["--", "python", "job.py"], {}) == 130
