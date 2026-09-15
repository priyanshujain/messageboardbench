# Population propensity experiment v1

This directory is the single entry point for the frozen SWE population experiment:
all 349 ImpossibleBench conflicting tasks, partitioned across 12 independent matched
control/board teams and three cohorts. The two arms use the same upstream prompt,
model, tasks, schedule, budgets and scorer; the board arm alone receives the neutral
`board_read` and `board_post` schemas and a team-persistent host store.

When `experiment.json` has status `ready`, no blockers, complete command arrays,
and a valid self-hash, run the whole lifecycle from this directory:

```sh
just start
```

That command validates the frozen manifest before any external action, writes local
lifecycle/provenance state, runs the configured local Python runner through only
`ssh://pj@100.68.126.75` using `scripts/remote_docker.py`, and then attempts the
allowlisted offline report, verification, and resource-summary steps. Offline steps
whose required artifacts exist run even if experiment execution returns nonzero;
missing-input steps are recorded as skipped. No shell command strings are evaluated.

Raw outputs and automatic, unreviewed reports stay under ignored `logs/`. Promotion
to a named `results/` bundle remains a separate reviewed evidence action. Source,
Python, credentials, logs, and results remain on this workstation; only container
operations go to the remote Docker daemon.

`just validate` is a free local manifest check and never invokes a model. Interrupted
runs resume from terminal assignment records when `just start` is called again;
derived reports from earlier attempts are retained under `logs/.../resume-history/`.
The first matched cohort pair acts as the engineering sentinel. Subsequent individual
sample errors are retained as outcomes and do not stop or rerun the population.
