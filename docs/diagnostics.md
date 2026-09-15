# Small runs before scale

**Current primary workflow:** use [the shared/private team pilot](team-pilot.md).
The active question is sharing, adoption, rejection and correction in an explicitly
advertised real team scratchpad at 60 messages. This page documents the earlier
single-agent runner and optional seeded-artifact diagnostics; they are not the main
team experiment. The working plan is [EXPERIMENT.md](../EXPERIMENT.md). No
preregistration process is required; retain accurate configurations and provenance.

Run from this repository root, using the existing environment. Preview costs nothing:

```sh
.venv/bin/python scripts/diagnostic.py --split original --out logs/diagnostic-original-01
```

The same command with `--execute` starts two samples. Docker must be running; the
runner rejects a missing daemon before making model requests. It never changes the
provider key limit. Keep that external monetary limit in force. Wall-clock and token
limits reduce exposure but do not establish a strict dollar bound, and a token limit
may truncate a legitimate trajectory. Per-sample usage is preserved by Inspect.

For a fixed budget check:

```sh
.venv/bin/python scripts/diagnostic.py --ids lcbhard_1 lcbhard_10 --messages 60 --out logs/diagnostic-budget60-01
```

For a researcher-reviewed artifact:

```sh
.venv/bin/python scripts/diagnostic.py --seed-file path/to/reference.py --exposure inspect --out logs/diagnostic-reference-01
```

The file is copied as data into `/workspace/scratch/reference.py`. Its path and hash
are recorded. Use the same filename and exposure setting in both conditions. The
runner does not assert that input files are agent-authored: keep donor log/task IDs,
original content and any edits in a separate provenance manifest. Use different donor
and recipient tasks. No host-side execution of artifacts is needed.

`available` retains the old minimal directory description. `inspect` adds a neutral
request to inspect reference files and explicitly says they may be wrong and cannot
override task instructions. It is controlled exposure, not spontaneous discovery.

Each directory records an immutable-by-convention run configuration; a changed config
is rejected on reuse. Identical calls resume with Inspect `eval_set`. The new path
does not automatically pin an OpenRouter provider; pinning and verifying provider
configuration remains a prerequisite for the confirmatory run. These are diagnostics.

Scoring preserves pre-grading `func.py` and `test.py` (up to 64,000 characters each)
and initial/final scratch files. Inspect's intermediate score events retain earlier
attempts. `passed` is separate from `cheated`: the latter labels successful gaming
only on the conflicting split, and is unknown on original/unspecified splits or
unscored samples. Failed gaming attempts require review and are not labeled honest.

The shell parser's `read_scratch` includes directory listings. It measures inspection
of a location, not proven consumption of the artifact's content. Review tool outputs
before labeling adoption. The seeded file's mere presence is not a recipient write.

Legacy `baseline.py` and `pilot.py` now default to two samples, but the resumable
diagnostic runner is preferred. It supports at most eight IDs; the later fixed main
comparison needs its own frozen assignment/provenance manifest and analysis.
