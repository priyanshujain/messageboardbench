# SWE population pilot 10 v1

## Purpose

Run a small end-to-end version of the homogeneous population experiment before the
full 349-task study. The pilot is intended to reveal concrete execution failures,
estimate resource use, and provide an initial descriptive control-versus-board
signal. It does not replace or alter the full frozen experiment.

## Frozen population and assignment

Ten task IDs are selected deterministically from all 349 official ImpossibleBench
SWE `conflicting` records at revision
`9c2d34f364b7229e8c0ff807c646100bdc18bbb5`. Selection ranks every instance ID by
SHA-256 of `swe-pilot-selection-v1:910:{instance_id}` and freezes the first ten in
`plan.json`. Selection does not inspect task content or outcomes.

Every selected task runs exactly once in each condition, giving 20 episodes:

- control: the upstream ImpossibleBench tools scaffold with no board;
- board: the same scaffold plus neutral `board_read` and `board_post` tools.

There is one matched team divided into two ordered cohorts of five tasks. The board
persists across both board cohorts and starts empty. There are no seeded posts,
mandatory reads, pushed notifications, scratchpad prompt, or collaboration prose.

## Held constant

The two arms use identical task IDs, issue/evaluator bytes, model
`openrouter/z-ai/glm-5.3-flash`, upstream tools prompt and strict contradiction
instruction, scorer, temperature 1, medium reasoning effort, 4,096 reasoning tokens,
100-message limit, 1,000,000-token episode limit, 1,800-second episode limit, ten
submissions, and isolated 8 GiB containers. Containers have no network and run only
through the remote x86-64 Docker daemon at `ssh://pj@100.68.126.75`.

The only treatment difference is the availability of the two board tools and access
to posts from other agents in the same board population. This is board versus no
board, so interface availability and peer-message availability are jointly treated.

## Outcomes and interpretation

The unattended deterministic report records evaluator success with protected tests,
test modification, failures and missingness, complete paired task outcomes, board
posts, reads, confirmed peer receipts, artifacts, transcripts, tokens, calls, and
elapsed resources. Intent, method publication, and attributed adoption remain manual
review outcomes and are not inferred automatically.

With only one treated board, statistical inference at the population-assignment level
is not meaningful. Any effect estimate and sign-flip value in the generic report are
descriptive pilot outputs. A zero, floor, or ceiling result is still a valid pilot
result and does not trigger task replacement or prompt tuning.

## Lifecycle

`just start` validates the frozen bundle, executes or resumes the 20 assignments,
and then generates `REPORT.md`, `report.json`, verification, and resource summaries.
The first matched cohort is the engineering sentinel; behavioral failures do not stop
it, while missing required execution artifacts do. No Codex monitoring is required.
