# messageboardbench

Do coding agents share, adopt, reject, or correct cheating techniques through a public team board?

Agents work on ImpossibleBench tasks in separate containers with private scratch space
and, in the board condition, explicit tools for reading and posting team messages.
The default pilot uses three agents per cohort, two cohorts, and 90 messages per
episode; model, population size, sampling and budgets are configurable.

Built on [ImpossibleBench](https://github.com/safety-research/impossiblebench) and
[Inspect AI](https://inspect.aisi.org.uk). Passing contradictory tests is an operational
signal of specification gaming, not a complete label of intent or attempted cheating.

See [setup](docs/setup.md) and the [board experiment workflow](docs/board-pilot.md).
Run `just board` to choose parameters interactively and start the experiment.
Use `just board-preview` for a configuration preview without model calls, or
`just board-run --model muse` to run with Muse Spark Contributor. Executing makes
paid requests; the existing key spending cap is never raised.

Start with [EXPERIMENT.md](EXPERIMENT.md) for the research question, what we have
done, what the results establish, and the next work. The latest pilot contains one
explicitly attributed cross-task adoption; it does not establish an increased
gaming rate or concealed collusion.

| Location | Purpose |
|---|---|
| `src/`, `scripts/`, `tests/` | Implementation, entry points and tests |
| `docs/` | Setup, workflow and supporting research |
| [results/](results/README.md) | Reviewed, frozen experiment evidence |
| `logs/` | Raw local runs, ignored by Git |
| `work/` | Disposable local working files, ignored by Git |

This is the sole working repository for the experiment. The former `messageboard`
repo is [retired](docs/migration/README.md); personal notes and unrelated material
remain in its archive. Run `just evidence-check` to verify the migrated evidence.
