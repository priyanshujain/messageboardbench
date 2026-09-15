# Offline analysis of preserved pilots

These entrypoints recompute existing evidence without model requests. Run from
`messageboardbench` with the installed `.venv`; output must be a fresh directory
outside the input evidence. The originals inside `results/` are frozen historical
scripts, including their original paths. Use these portable copies for reanalysis.

```sh
.venv/bin/python scripts/analysis/board_synthesis.py --out work/glm-interface-reanalysis
.venv/bin/python scripts/analysis/token_audit.py --out work/historical-token-reanalysis
```

`board_synthesis.py` defaults to `results/board-pilot-sept8` and
`results/board-interface-v2-sept8`; override with `--results-v1` / `--results-v2`.
It joins the twelve v2 episodes to existing reviewed labels and compares descriptive
metrics with v1. It does not classify new trajectories or support arbitrary runs.
`review_file` paths in its outputs are relative to the input v2 evidence directory.

`token_audit.py` defaults to `logs/`; override with `--logs`. It requires all five
historical run directories in its frozen inclusion list. It reproduces that audit's
metrics; newly created logs are excluded. Neither script infers honesty from a
failed attempt, estimates causal effects, or modifies the source reports/logs.

For exporting a new run before trajectory review, use `just board-report`.

`board_resources.py --run logs/RUN --export results/RUN/final-export --out results/RUN/resource-summary.json`
summarizes arbitrary completed exports by condition and task split, including token
components, episode time, submissions, communication counts and recorded account
usage. It assigns no behavioral labels; reasoning tokens remain a subset of output.

For a new completed run, validate export integrity and replay captured final suites:

```sh
.venv/bin/python scripts/analysis/validate_board_export.py --run logs/RUN --export results/RUN/final-export --out results/RUN/verification.json
.venv/bin/python scripts/analysis/replay_board_artifacts.py --run logs/RUN --export results/RUN/final-export --out results/RUN/artifact-replays
```

Validation checks source/log/snapshot hashes, actual sample settings and task inputs,
matched schedule, exact delivered board responses, preserved test bytes, and token
arithmetic including cache reads/writes. It reports failures without assigning behavior
labels. Replay executes captured code only inside separate unprivileged Docker
containers with networking disabled, capabilities dropped and no mounts; bytes enter
through `docker cp` tar stdin. Containers have a disposable writable layer and are
removed afterward. Captured suites alone do not classify gaming: add targeted probes
and review trajectories. Output destinations must be fresh.
