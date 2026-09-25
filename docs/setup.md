# Setup

Use the repository's existing local `.venv` for Python. All Docker-backed checks and
experiments use the x86-64 daemon at `ssh://pj@100.68.126.75` through
`scripts/remote_docker.py`; see [remote-docker.md](remote-docker.md). Source, Python,
credentials, logs, and results stay on this workstation. Do not copy the repository or
create a Python environment on the Docker host.

```
uv sync
uv pip install -e /path/to/impossiblebench --no-deps
```

## Why --no-deps

It is required, not a shortcut. ImpossibleBench declares
`inspect_evals[swe_bench] @ git+https://github.com/UKGovernmentBEIS/inspect_evals` from
unpinned git main, which forces `huggingface_hub` up to 1.2+, and `swebench>=4.0.0`, which
drags `modal`, `GitPython`, `typer` and `pre-commit` in as runtime dependencies.

The LiveCodeBench path we use imports none of it. Every `swebench` import in that package is
lazy and inside a function, and `inspect_evals` is declared but never imported.

`--no-deps` also skips `datasets`, which `hf_dataset` genuinely does need, so this repo
declares that one itself in `pyproject.toml`.

The staged SWE-bench path is intentionally separate. Its pinned optional dependencies
and free nochange/oracle gate are documented in [swe-validation.md](swe-validation.md);
do not install them for LiveCodeBench-only work.

Two things to know. `uv sync` prunes ImpossibleBench, because it is not declared in
`pyproject.toml`, so rerun the install line after every sync. `just install` does both.
And ImpossibleBench mutates `sys.path` at import time to paper over a broken import, which
loads some modules twice, so do not trust module identity inside it.

## The working directory

`compose.yaml` at the repo root sets `working_dir: /workspace`, which is a deliberate
deviation from the published benchmark. The file itself explains why.

Inspect looks for `compose.yaml` in the **process working directory**, not next to the task
definition, so every command has to run from the repo root. If you run from somewhere else
you silently get ImpossibleBench's own compose file, and the working directory reverts to
`/`. The justfile recipes handle this.

## Checks that cost nothing

```
just smoke      # fake model locally; task container on the remote Docker daemon
just test       # offline unit tests, no network and no provider beyond mockllm
```

`just smoke` should end with `status: success` and a real score. If the tracebacks in that
score mention `/workspace/test.py`, the working directory override is live.

## Spending money

`.env` holds `OPENROUTER_API_KEY` and is gitignored. The key carries a $2 cap as a fuse.

For a separate Kimi K3 or DeepSeek SWE population using ClinePass, put
`CLINE_API_KEY` in the same local `.env`. The SWE runner pins Cline's
`https://api.cline.bot/api/v1` endpoint. Use one of the exact Inspect model IDs
`openai-api/cline/cline-pass/kimi-k3`,
`openai-api/cline/cline-pass/deepseek-v4-pro`, or
`openai-api/cline/cline-pass/deepseek-v4-flash` in a new frozen plan. GLM-5.3 Flash
stays on OpenRouter; do not mix the providers in one plan. ClinePass account quota
is not available from the documented API, so its account snapshots are marked
unavailable rather than using the OpenRouter balance. New ClinePass plans omit
the unverified OpenRouter reasoning settings; provider compatibility has not
been checked with a paid call.

Watch per-request `prompt_n` on any run longer than a few turns. Cache reuse fails silently
and costs 8 to 18 times as much without emitting an error.
