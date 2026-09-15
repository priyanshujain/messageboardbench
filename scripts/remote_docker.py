"""Run a local command against the experiment's Docker daemon over SSH.

The command itself runs locally. Only Docker CLI requests made by it are directed to
the remote daemon. A server architecture check fails closed before the command starts.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from urllib.parse import urlsplit


DEFAULT_DOCKER_HOST = "ssh://pj@100.68.126.75"
EXPECTED_SERVER = "linux/amd64"


def docker_host(environ: dict[str, str]) -> str:
    return environ.get("MBB_DOCKER_HOST", DEFAULT_DOCKER_HOST)


def validate_host(host: str) -> None:
    parsed = urlsplit(host)
    if (
        parsed.scheme != "ssh"
        or not parsed.hostname
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError(
            "MBB_DOCKER_HOST must be an ssh://[user@]host URI without a password, "
            "path, query, or fragment"
        )


def check_daemon(host: str, environ: dict[str, str]) -> str:
    env = dict(environ)
    env["DOCKER_HOST"] = host
    result = subprocess.run(
        [
            "docker",
            "version",
            "--format",
            "{{.Server.Os}}/{{.Server.Arch}}",
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    server = result.stdout.strip()
    if server != EXPECTED_SERVER:
        raise RuntimeError(
            f"Refusing Docker server {server!r}; expected {EXPECTED_SERVER!r} at {host}"
        )
    return server


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="local command to run; place it after -- (omit it for a connection check)",
    )
    return p


def main(argv: list[str] | None = None, environ: dict[str, str] | None = None) -> int:
    args = parser().parse_args(argv)
    env = dict(os.environ if environ is None else environ)
    host = docker_host(env)
    try:
        validate_host(host)
        server = check_daemon(host, env)
    except (ValueError, RuntimeError, subprocess.SubprocessError, OSError) as exc:
        print(f"Remote Docker preflight failed: {exc}", file=sys.stderr)
        return 2

    print(f"Remote Docker ready: {host} ({server})", flush=True)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        return 0
    env["DOCKER_HOST"] = host
    try:
        return subprocess.run(command, env=env).returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
