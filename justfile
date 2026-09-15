# All recipes run from the repo root, because inspect resolves compose.yaml against the
# process working directory. See docs/setup.md.

impossiblebench := "../impossiblebench"
remote-docker := ".venv/bin/python scripts/remote_docker.py --"

# Sync dependencies, then re-add ImpossibleBench (uv sync prunes it).
install:
    uv sync
    uv pip install -e {{impossiblebench}} --no-deps

# Install the isolated SWE validation extra without immediately pruning it again.
swe-install:
    env UV_CACHE_DIR=work/uv-cache-swe uv sync --extra swe
    env UV_CACHE_DIR=work/uv-cache-swe uv pip install -e {{impossiblebench}} --no-deps

# Offline unit tests. No network, no provider beyond mockllm.
test:
    env PYTHONPATH=. uv run pytest -q

# The real task against a fake model. Free.
smoke:
    {{remote-docker}} uv run python scripts/smoke_mock.py

# Confirms the daemon is up and pre-pulls the image. Should print "/".
docker-check:
    {{remote-docker}} docker run --rm aisiuk/inspect-tool-support pwd

# Confirms the model slug, the key and tool support. Costs about a cent.
model-check:
    uv run python scripts/model_check.py

# Development only: two tasks per split by default.
baseline:
    {{remote-docker}} uv run python -u scripts/baseline.py conflicting original

# The forked task against a fake model. Free. Checks the scratch wiring.
smoke-scratch:
    {{remote-docker}} uv run python scripts/smoke_scratch.py

# Development only: two agents by default. Prefer diagnostic for resumable runs.
pilot:
    {{remote-docker}} uv run python -u scripts/pilot.py

# Rebuild the CSV and hand-read file from an existing log, no re-run.
report log_dir="logs/pilot":
    uv run python scripts/report.py {{log_dir}}

# Proves the scorer captures a file an agent leaves in scratch. Free, needs Docker.
verify-snapshot:
    {{remote-docker}} uv run python scripts/verify_snapshot.py

# Writes the checks and the raw agent commands side by side, to read by hand.
calibrate log_dir="logs/pilot":
    uv run python scripts/calibrate.py {{log_dir}}

# Preview a two-sample run without spending. Add --execute manually after review.
diagnostic:
    .venv/bin/python scripts/diagnostic.py --out logs/diagnostic-01

# Ask for model, team sizes, task sampling and budgets, then run (paid).
board:
    {{remote-docker}} .venv/bin/python scripts/run_board.py --interactive --execute

# Show the board run configuration without model calls. Accepts runner flags.
[positional-arguments]
board-preview *args:
    .venv/bin/python scripts/run_board.py --preview "$@"

# Run a configured board experiment (paid). Accepts the same flags as preview.
[positional-arguments]
board-run *args:
    {{remote-docker}} .venv/bin/python scripts/run_board.py --execute "$@"

# Export transcripts, artifacts and exact peer-message delivery evidence offline.
[positional-arguments]
board-report run out:
    .venv/bin/python scripts/board_report.py --run "$1" --out "$2"

# Check isolation and board tools with a mock model and real Docker (free).
[positional-arguments]
board-check out:
    {{remote-docker}} .venv/bin/python scripts/check_board_infrastructure.py --out "$1"

# Verify the configured remote daemon without starting a container.
remote-docker-check:
    .venv/bin/python scripts/remote_docker.py

# Preview a frozen no-communication A-D development calibration; never calls a model.
[positional-arguments]
prompt-calibration-preview manifest out:
    .venv/bin/python scripts/run_prompt_calibration.py --manifest "$1" --out "$2"

# Execute a frozen development calibration (paid) using only the remote Docker daemon.
[positional-arguments]
prompt-calibration-run manifest out:
    {{remote-docker}} .venv/bin/python scripts/run_prompt_calibration.py --manifest "$1" --out "$2" --execute

# Resume only from a recorded between-assignment boundary with the identical plan.
[positional-arguments]
prompt-calibration-resume manifest out:
    {{remote-docker}} .venv/bin/python scripts/run_prompt_calibration.py --manifest "$1" --out "$2" --execute --resume

# Freeze the separate adaptive prompt-E plan; never loads data or calls a model.
[positional-arguments]
prompt-e-freeze *args:
    .venv/bin/python scripts/prompt_e_calibration.py "$@"

# Preview a frozen prompt-E plan; never loads data, starts Docker, or calls a model.
[positional-arguments]
prompt-e-preview manifest out:
    .venv/bin/python scripts/run_prompt_calibration.py --manifest "$1" --out "$2"

# Execute prompt E only after explicit inspection/authorization (paid, remote Docker only).
[positional-arguments]
prompt-e-run manifest out:
    {{remote-docker}} .venv/bin/python scripts/run_prompt_calibration.py --manifest "$1" --out "$2" --execute

# Preview the one-shot frozen prompt-D validation; never calls a model.
[positional-arguments]
prompt-validation-preview manifest audit out:
    .venv/bin/python scripts/run_prompt_validation.py --manifest "$1" --validation-audit "$2" --out "$3"

# Execute prompt-D validation once (paid) on the remote Docker daemon; no resume path.
[positional-arguments]
prompt-validation-run manifest audit out:
    {{remote-docker}} .venv/bin/python scripts/run_prompt_validation.py --manifest "$1" --validation-audit "$2" --out "$3" --execute

# Preview a pinned SWE nochange/oracle validation (local metadata only).
[positional-arguments]
swe-preview *args:
    .venv/bin/python scripts/validate_swe.py "$@"

# Run four free SWE validation containers on the remote x86-64 daemon.
[positional-arguments]
swe-validate *args:
    {{remote-docker}} .venv/bin/python scripts/validate_swe.py --execute "$@"

# Verify that migrated experiment evidence still matches its original hashes.
evidence-check:
    .venv/bin/python scripts/verify_evidence.py
