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

# Confirms the daemon is up and pre-pulls the image so the first eval does not
# time out on a cold pull. Should print "/".
docker-check:
    docker run --rm aisiuk/inspect-tool-support pwd
