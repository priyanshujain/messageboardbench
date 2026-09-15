"""Host-side shared-team infrastructure. Nothing here calls a model provider."""
from __future__ import annotations

import hashlib
import errno
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import uuid

TEAM_COMPOSE = Path(__file__).resolve().parents[2] / "compose.team.yaml"
IMAGE = "aisiuk/inspect-tool-support"


def render_team_compose(team_dir: Path, config_path: Path) -> Path:
    """Render a literal compose file usable during Inspect's pre-sample task init.

    Inspect enumerates services before sample metadata interpolation, so a required
    metadata variable cannot remain in the configuration passed to Task. The runner
    must pass a directory created by prepare_team_directory (or validated against
    its run root with validate_team_directory).
    """
    import yaml

    directory = Path(team_dir)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Team mount source must be an existing nonsymlink directory")
    directory = directory.resolve(strict=True)
    if directory.parent.name != "shared":
        raise ValueError("Team mount source must be directly inside a shared directory")
    _identifier(directory.name)
    config = yaml.safe_load(TEAM_COMPOSE.read_text())
    config["services"]["default"]["volumes"][0]["source"] = str(directory)
    destination = Path(config_path).absolute()
    if destination.resolve().is_relative_to(directory):
        raise ValueError("Compose configuration must stay outside the agent mount")
    destination.parent.mkdir(parents=True, exist_ok=True)
    contents = json.dumps(config, indent=2) + "\n"
    if destination.exists():
        if destination.read_text() != contents:
            raise ValueError("Existing compose configuration differs; use a new path")
    else:
        destination.write_text(contents)
    return destination


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", value):
        raise ValueError("Team and agent identifiers must be simple names")
    return value


def validate_team_directory(path: Path, run_dir: Path) -> Path:
    """Accept only an existing, nonsymlink team directly below run/shared."""
    root = run_dir.resolve() / "shared"
    candidate = Path(path).absolute()
    if root.is_symlink() or candidate.is_symlink():
        raise ValueError("Shared directories cannot be symbolic links")
    resolved = candidate.resolve(strict=True)
    if resolved.parent != root or not resolved.is_dir():
        raise ValueError("Team directory must be directly within run_dir/shared")
    _identifier(resolved.name)
    return resolved


def prepare_team_directory(run_dir: Path, team_id: str, agent_ids: list[str]) -> Path:
    """Make a fresh team namespace. Reuse fails to prevent accidental contamination."""
    _identifier(team_id)
    if not agent_ids or len(set(agent_ids)) != len(agent_ids):
        raise ValueError("Provide distinct agent identifiers")
    for agent_id in agent_ids:
        _identifier(agent_id)
    root = run_dir.resolve() / "shared"
    if root.is_symlink():
        raise ValueError("Shared directory cannot be a symbolic link")
    root.mkdir(parents=True, exist_ok=True)
    team = root / team_id
    team.mkdir()  # deliberately fail if an earlier experiment used this directory
    (team / "board").mkdir()
    (team / "agents").mkdir()
    for agent_id in agent_ids:
        (team / "agents" / agent_id).mkdir()
    return validate_team_directory(team, run_dir)


def snapshot_team_directory(path: Path, max_files: int = 1000,
                            max_bytes: int = 64000) -> dict:
    """Bounded snapshot without following agent-created symlinks or reading devices.

    This is team state, not proof that a particular agent wrote/read a file. During
    concurrent execution it is not an atomic snapshot; archive again between waves.
    sha256 covers the captured bytes (explicitly a prefix for truncated files).
    Entries deleted or replaced while scanning receive explicit transient records.
    Other file/directory errors propagate as infrastructure failures.
    """
    if max_files < 1 or max_bytes < 1:
        raise ValueError("Snapshot limits must be positive")
    if path.is_symlink():
        raise ValueError("Snapshot root cannot be a symbolic link")
    root_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    records: dict = {}

    def walk(directory_fd: int, prefix: str = "") -> None:
        for name in sorted(os.listdir(directory_fd)):
            if len(records) >= max_files:
                raise ValueError("Shared snapshot exceeded its entry limit")
            relative = f"{prefix}/{name}" if prefix else name
            try:
                capture(directory_fd, name, relative)
            except OSError as error:
                # Atomic saves commonly unlink/rename temporary files while another
                # agent is scanning. O_NOFOLLOW also rejects a symlink substituted
                # between stat and open; record that race without following it.
                if error.errno not in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
                    raise
                records[relative] = {
                    "kind": "transient", "skipped": True,
                    "reason": "entry disappeared or changed type during snapshot",
                    "errno": error.errno,
                }

    def capture(directory_fd: int, name: str, relative: str) -> None:
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode):
            records[relative] = {"kind": "symlink", "skipped": True}
        elif stat.S_ISDIR(info.st_mode):
            records[relative] = {"kind": "directory"}
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                         dir_fd=directory_fd)
            try:
                walk(fd, relative)
            finally:
                os.close(fd)
        elif stat.S_ISREG(info.st_mode):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=directory_fd)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    records[relative] = {"kind": "transient", "skipped": True,
                                         "reason": "file changed type during snapshot"}
                    return
                with os.fdopen(fd, "rb", closefd=False) as stream:
                    data = stream.read(max_bytes + 1)
            finally:
                os.close(fd)
            truncated = len(data) > max_bytes
            data = data[:max_bytes]
            records[relative] = {
                "kind": "file", "content": data.decode("utf-8", errors="replace"),
                "sha256": hashlib.sha256(data).hexdigest(),
                "captured_bytes": len(data), "truncated": truncated,
            }
        else:
            records[relative] = {"kind": "special", "skipped": True}

    try:
        walk(root_fd)
    finally:
        os.close(root_fd)
    return records


def validate_shared_docker(run_dir: Path) -> dict:
    """Explicit no-model integration check using two disposable Docker services.

    Uses the production image, mount target, workdir and network restriction.
    Fails if Docker is unavailable. Leaves the compose file, shared evidence and
    result on the host; removes only the containers created by this check.
    """
    subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                   check=True, capture_output=True, text=True, timeout=15)
    check_dir = run_dir.resolve() / f"infrastructure-check-{uuid.uuid4().hex[:10]}"
    team = prepare_team_directory(check_dir, "validation", ["agent-1", "agent-2"])
    sentinel = check_dir / "host-only-log.txt"
    sentinel.write_text("This researcher log must never be mounted.\n")
    service = {
        "image": IMAGE, "command": ["tail", "-f", "/dev/null"],
        "working_dir": "/workspace", "init": True, "network_mode": "none",
        "stop_grace_period": "1s", "mem_limit": "1gb",
        "volumes": [{"type": "bind", "source": str(team),
                     "target": "/workspace/scratch", "bind": {"create_host_path": False}}],
    }
    compose = check_dir / "compose.validation.json"
    compose.write_text(json.dumps({"services": {"agent1": service, "agent2": service}}, indent=2))
    project = "mbb-check-" + uuid.uuid4().hex[:10]
    command = ["docker", "compose", "-p", project, "-f", str(compose)]

    def run(*args: str, timeout: int = 60) -> str:
        return subprocess.run([*command, *args], check=True, capture_output=True,
                              text=True, timeout=timeout).stdout

    try:
        run("up", "-d", timeout=300)
        run("exec", "-T", "agent1", "python", "-c",
            "from pathlib import Path; Path('/workspace/func.py').write_text('agent-one'); "
            "Path('/workspace/scratch/agents/agent-1/note.txt').write_text('hello-team')")
        run("exec", "-T", "agent2", "python", "-c",
            "from pathlib import Path; "
            "assert Path('/workspace/scratch/agents/agent-1/note.txt').read_text() == 'hello-team'; "
            "assert not Path('/workspace/func.py').exists(); "
            "Path('/workspace/func.py').write_text('agent-two'); "
            "Path('/workspace/scratch/board/reply.txt').write_text('received')")
        run("exec", "-T", "agent1", "python", "-c",
            "from pathlib import Path; "
            "assert Path('/workspace/func.py').read_text() == 'agent-one'; "
            "assert Path('/workspace/scratch/board/reply.txt').read_text() == 'received'")
        image_evidence = {}
        for agent in ("agent1", "agent2"):
            container = run("ps", "-q", agent).strip()
            inspected = subprocess.run(["docker", "inspect", container], check=True,
                                      capture_output=True, text=True, timeout=30)
            container_info = json.loads(inspected.stdout)[0]
            mounts = container_info["Mounts"]
            image_id = container_info["Image"]
            image_inspected = subprocess.run(["docker", "image", "inspect", image_id],
                                            check=True, capture_output=True,
                                            text=True, timeout=30)
            image_info = json.loads(image_inspected.stdout)[0]
            image_evidence[agent] = {
                "requested_image": IMAGE, "image_id": image_id,
                "repo_digests": image_info.get("RepoDigests") or [],
            }
            assert len(mounts) == 1, f"Unexpected additional mounts: {mounts}"
            assert mounts[0]["Source"] == str(team)
            assert mounts[0]["Destination"] == "/workspace/scratch"
            run("exec", "-T", agent, "python", "-c",
                f"from pathlib import Path; assert not Path({str(sentinel)!r}).exists(); "
                "assert not Path('/workspace/host-only-log.txt').exists()")
        result = {"success": True, "cross_container_visibility": True,
                  "grading_files_isolated": True, "only_team_directory_mounted": True,
                  "images": image_evidence,
                  "snapshot": snapshot_team_directory(team), "compose": str(compose)}
        (check_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        return result
    finally:
        run("down", "--timeout", "1", timeout=60)
