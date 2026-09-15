# Working in messageboardbench

This is the canonical workspace for the experiment. Read `EXPERIMENT.md` for the
current question, completed results, limitations and next work. The old
`../archive/messageboard-20260908` repository is retired; its plans and instructions
are historical. Do not create experiment files there or in a sibling scratchpad.

- Use Codex subagents for analysis and any substantial, independently delegable
  work: literature review, trajectory review, artifact validation, implementation
  and review. Assign clear ownership; the primary agent checks and integrates.
- These are internal research assistants, not experimental agents. Do not change
  the experimental population to include subagents without PJ requesting it.
- Keep root files limited to project entry points and configuration. Put reusable
  code in `src/` or `scripts/`, tests in `tests/`, maintained explanations in `docs/`,
  raw runs in ignored `logs/`, and reviewed evidence in named `results/` bundles.
- Use ignored `work/` for disposable agent working files. Never use a user's
  personal notes or scratchpad for generated outputs. Promote useful work into an
  existing documented location; do not leave competing PLAN/STATUS documents.
- Treat migrated `results/` bundles as frozen evidence. Preserve transcript,
  artifact and provenance bytes, including historical paths. Use the migration
  manifest to resolve old paths; write recomputations to fresh output directories.
- Use the existing `.venv/bin/python` and the documented `just board*` workflow.
  `muse` means `openrouter/meta/muse-spark-1.3-contributor`; no silent model fallback.
- Keep source, Python execution, credentials, logs and results on this workstation.
  For every Docker-backed check or experiment, use only the remote x86-64 Docker
  daemon at `ssh://pj@100.68.126.75`; do not copy or stage the repository on that host.
- Do not launch paid experiments merely to test code or reorganize files. Use
  offline tests and mock models. Existing user authorization governs actual runs.
- Distinguish publication, delivered peer receipt, attributed adoption, rejection,
  and independent discovery. A passing contradictory test or similar code alone
  does not establish transmission, concealed collusion, or monitor evasion.
- After analyzing a completed experiment, write the maintained interpretation to
  lowercase `analysis.md` inside that experiment's `experiments/<id>/` folder. Keep
  automatic output distinct from reviewed behavioral conclusions and link the exact
  evidence used.
- Prefer a clean code/config commit before launching each new experiment. After the
  run and analysis, commit the associated code, frozen configuration, documentation,
  and `analysis.md` after checking for secrets and accidental raw logs. Record the
  commit hash in the handoff. The executed source snapshot remains authoritative if
  code changed during or after the run.
