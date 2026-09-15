# Communication-holdout audit

The confirmatory board runner accepts only an explicitly semantically reviewed audit
tied to an immutable Hugging Face dataset commit. Audit generation is local and does
not invoke Docker or a behavioral model provider, and it does not inspect model
outcomes. The audit records its reviewer type without representing an internal Codex
review as human review.

The workflow deliberately has two stages. A machine-generated candidate is never
run-ready. It checks that each reserved task exists in the original and conflicting
splits, hashes the exact prompt and evaluator bytes, parses the Python tests, and
looks for one added assertion whose candidate call exactly matches an original
assertion but expects a different value. These checks establish useful structural
facts; they do not establish that the specification is coherent or that the
original expected values are semantically correct.

## 1. Generate a candidate and review template

Use an already selected full dataset commit when possible:

```sh
.venv/bin/python scripts/audit_lcb_holdout.py candidate \
  --dataset-revision 98650ffc3f28a01b261669b6d19fcd7773823710 \
  --out work/holdout-audit-clean-pool-candidate-v2.json \
  --review-template work/holdout-audit-clean-pool-review-v2.json
```

Omitting `--dataset-revision` resolves the repository's current Hub revision once
and records the returned 40-character commit. It does not leave a moving branch name
in the audit. Candidate and review files must be new so prior evidence is not
silently overwritten.

The same command can prepare the separately reserved prompt-D validation partition:

```sh
.venv/bin/python scripts/audit_lcb_holdout.py candidate \
  --partition validation \
  --dataset-revision DATASET_COMMIT \
  --out work/prompt-d-validation-audit-candidate.json \
  --review-template work/prompt-d-validation-audit-review.json
```

That candidate contains both original and conflicting rows for every frozen
validation ID because the validation runner executes both splits. It still requires
semantic review and the ordinary freeze stage before it becomes runnable.

The candidate contains the exact task prompt, original evaluator, conflicting
evaluator, their hashes, and extracted contradiction evidence for the reviewed
11-task pool: `lcbhard_7`, `lcbhard_13`, `lcbhard_41`, `lcbhard_42`, `lcbhard_44`,
`lcbhard_46`, `lcbhard_49`, `lcbhard_52`, `lcbhard_66`, `lcbhard_68`, and
`lcbhard_70`. Keep it in ignored `work/`; it is a review packet, not a result. Its
status is always `needs_semantic_review`. Older candidate packets are retained as
evidence and must not be overwritten.

## 2. Review semantics

For every decision in the review JSON, the reviewer must read the exact review
material and determine that:

- the task specification and entry point form a valid coding task;
- the original evaluator's relevant expected answers agree with the specification;
- the conflicting evaluator contains a genuinely incompatible output for the same
  input, rather than an AST coincidence or another kind of mutation.

Set `task_validated` and `evaluator_validated` to `true` only after those checks.
Replace the reviewer and timestamp placeholders and add task-specific notes. Set
`reviewer_type` to `human` for a named human reviewer. Alternatively,
`internal_codex_dual_review` requires exactly two distinct named internal reviewers,
distinct roles, and the path and SHA-256 of each review artifact. This second path
must always remain labeled as internal Codex review, never human review. Leave a pair
false if it is ambiguous; do not freeze it merely because all mechanical checks
passed. `no_model_outcomes_inspected` records the holdout boundary and must remain
true.

## 3. Freeze the reviewed audit

```sh
.venv/bin/python scripts/audit_lcb_holdout.py freeze \
  --candidate work/holdout-audit-clean-pool-candidate-v2.json \
  --review work/holdout-audit-clean-pool-review-v2.json \
  --out work/holdout-audit-clean-pool-ready-v2.json
```

Freeze fails unless the review names and correctly types its reviewer(s), has an
ISO-8601 timestamp, approves every exact candidate pair, includes non-placeholder
task-specific notes, and binds to the SHA-256 of the candidate file's exact bytes.
It also fails if any mechanical check failed. The output is `schema_version: 2`,
`status: ready`, with the exact `approved_pairs` fields consumed by
`scripts/board_pilot.py`. The board runner checks the retained review provenance,
independently reloads the pinned dataset, and recomputes prompt/test hashes before
creating episodes.

Use the same revision and ready file together:

```sh
just board-preview --dataset-revision 98650ffc3f28a01b261669b6d19fcd7773823710 \
  --holdout-audit work/holdout-audit-clean-pool-ready-v2.json --out logs/reviewed-preview
```

Generating or freezing this audit does not authorize a paid experiment.
