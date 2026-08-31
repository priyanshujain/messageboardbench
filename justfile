# All recipes run from the repo root, because inspect resolves compose.yaml against the
# process working directory. See docs/setup.md.

impossiblebench := "../impossiblebench"

# Sync dependencies, then re-add ImpossibleBench (uv sync prunes it).
install:
    uv sync
    uv pip install -e {{impossiblebench}} --no-deps

# Offline unit tests. No network, no provider beyond mockllm.
test:
    uv run pytest -q

# The real task against a fake model. Free.
smoke:
    uv run python scripts/smoke_mock.py

# Confirms the daemon is up and pre-pulls the image. Should print "/".
docker-check:
    docker run --rm aisiuk/inspect-tool-support pwd

# Confirms the model slug, the key and tool support. Costs about a cent.
model-check:
    uv run python scripts/model_check.py

# Phase 1: cheat rate on conflicting, solve rate on original. About $1.
baseline:
    uv run python -u scripts/baseline.py conflicting original

# The forked task against a fake model. Free. Checks the scratch wiring.
smoke-scratch:
    uv run python scripts/smoke_scratch.py

# Phase 2: thirty agents with a scratch directory. Does anybody write anything?
pilot:
    uv run python -u scripts/pilot.py

# Rebuild the CSV and hand-read file from an existing log, no re-run.
report log_dir="logs/pilot":
    uv run python scripts/report.py {{log_dir}}

# Proves the scorer captures a file an agent leaves in scratch. Free, needs Docker.
verify-snapshot:
    uv run python scripts/verify_snapshot.py
