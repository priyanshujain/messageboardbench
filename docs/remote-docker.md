# Remote Docker execution

All experiment containers run on the authorized x86-64 Docker daemon at
`pj@100.68.126.75`. Python, source code, run manifests, logs, and analysis remain on
the local machine. The maintained `just` recipes use `scripts/remote_docker.py` to
set `DOCKER_HOST=ssh://pj@100.68.126.75`, verify that the server reports
`linux/amd64`, and then launch the local Python command. Offline unit tests remain
local and do not receive `DOCKER_HOST`.

Check the connection without starting a container:

```sh
.venv/bin/python scripts/remote_docker.py
```

Run a Docker-backed command directly only through the wrapper:

```sh
.venv/bin/python scripts/remote_docker.py -- \
  .venv/bin/python scripts/check_board_infrastructure.py --out logs/FRESH
```

`MBB_DOCKER_HOST` may override the endpoint with another password-free SSH URI.
The wrapper deliberately ignores an ambient `DOCKER_HOST`, preventing an accidental
fallback to a local daemon. SSH authentication and host-key verification must already
work noninteractively; no private key or API credential is copied by the wrapper.

## What is local and what is remote

The Docker CLI and Inspect process run locally. Compose files, generated task inputs,
SQLite boards, logs, and source snapshots are local. Images, containers, networks,
volumes, and container writable layers live on the remote daemon. Inspect transfers
task files through Docker operations; it does not require a checkout on the remote
host.

Bind-mount sources are interpreted by the daemon, not by the local Docker client.
Consequently `compose.team.yaml` and the retired shared-directory experiment are not
compatible with this workflow: their local host paths do not exist on the daemon host.
The current private-scratch/public-board design uses `compose.yaml`, which has no bind
mount and keeps the board in the local host process.

Do not use a local-path bind mount as a workaround. Do not stage a repository, Python
environment, dataset cache, or secrets on the remote host. For SWE-bench, prefer an
existing or registry-pulled instance image. A local Docker build sends its build context
to the remote daemon and retains it in image/build cache, so it requires a separate
review before use.

## SWE-bench limitations

The current local environment does not install the `swebench` or Python `docker`
packages. The upstream ImpossibleBench image builder imports the Python Docker SDK,
while normal Inspect sandbox operation uses the Docker CLI. Adding SWE support therefore
requires pinned local dependencies and verification that the SDK's SSH transport works,
or a CLI-only image pull path.

The upstream adapter also needs correctness fixes before a dummy run is evidence of
readiness: its generated `allow_internet=False` Compose network is marked
`internal: false`; test-patch application can fail without aborting; and its scorer
uses overall process exit status while the official per-test parser is disabled. Keep
dummy `nochange`/`oracle` validation separate from paid model execution, pin the dataset
revision and image digest, and save raw per-test output.
