# Can coding agents transmit evaluator-gaming methods?

Updated September 25, 2026. This repository studies how coding agents respond to contradictory SWE-bench evaluators and whether shared channels transmit evaluator-gaming methods. The current series assigns the same 20 tasks to GLM 5.3 Flash, Muse Spark 1.3 Contributor, and DeepSeek V4 Pro 0813.

## Current question

We measure four separate families of outcomes: cheating progression, mechanism and scope, persistence under pressure, and information or governance behavior. Communication claims distinguish publication, exact peer receipt, attributed adoption, candidate unattributed adoption, rejection, republication, and independent discovery. A scorer pass or similar code alone does not establish transmission.

Each model has a separate board or scratchpad within a scenario. Agents never share state across models. New offline scenarios disable agent network access; the internet scenario enables it through a project-specific bridge. Fresh graders remain isolated.

## Scenario status

| Scenario | Status | Maintained record |
| --- | --- | --- |
| Isolated baseline | Complete, 60 selected episodes | [Analysis](experiments/baseline-swebench/analysis.md) |
| Isolated offline control | Prepared, not started | [Design](experiments/swe-isolated-offline/DESIGN.md) |
| Shared scratchpad | Complete, 60 original episodes | [Analysis](experiments/swe-shared-scratch/analysis.md) |
| Shared board | Analyzed; GLM and Muse complete, DeepSeek has 10 readable episodes | [Analysis](experiments/swe-shared-board/analysis.md) |
| Board and organizer feedback | Complete, 60 selected episodes | [Analysis](experiments/swe-board-feedback/analysis.md) |
| Board and internet | Prepared, not started | [Design](experiments/swe-board-internet/DESIGN.md) |
| Board and token awareness | Running under PJ's control | [Design](experiments/swe-board-token-budget/DESIGN.md) |

The [series protocol](docs/swe-scenario-series.md) records the frozen task assignment, model routes, interventions, comparisons, and common limitations.

## Findings so far

The baseline produced successful reviewed gaming on valid contradictory tasks in 3/15 GLM, 8/15 Muse, and 1/15 DeepSeek assignments. It had no peer communication. Its agent containers had network access, DeepSeek used a different provider, and 13 selected episodes came from recovery attempts, so it is a descriptive baseline rather than the matched offline control.

The shared scratchpad exposed exact peer-authored bytes to 12 recipient episodes through 18 deliveries. None of eight captured item groups contained an actionable gaming method, and no adoption was observed. Muse wrote nothing to the shared directory. Seventeen episodes had infrastructure-null fresh grades.

The shared board produced three actionable Muse publications, nine recipients of actionable posts, four medium-confidence candidate unattributed adoptions, and two republications. All four candidate artifacts passed fresh grading. No recipient credited a peer, so attributed adoption remains zero. GLM and DeepSeek had no actionable publication. DeepSeek stopped after ten behavior-readable episodes because the OpenRouter key reached its total limit.

The organizer-feedback scenario recorded 24 accepted contradiction reports. Three Muse agents reported a contradiction before their first observed gaming attempt and later passed with gaming patches. The public board carried no actionable gaming method and showed no adoption. Reporting is observed channel use, not an honesty label, and raw differences from the shared-board run do not identify a feedback effect.

## Limits

Semantic review classifies 15 tasks as contradictory, three as malformed, and two as satisfiable. Report valid contradictory denominators separately from assigned counts. Each model and condition has one evolving shared history, so 20 episodes are dependent observations rather than 20 independent team replications. The isolated offline control is still pending, which prevents matched causal estimates for scratchpad and board access. Reviews are Codex assisted rather than blinded human annotation, and Muse's full chain of thought is unreadable in recorded provider blocks.

Raw trajectories, source snapshots, and run records live in `logs/` for retained experiments. Reviewed metrics, plots, plans, analyses, and required small assets live in the retained experiment folders. Historical experiment definitions and logs are preserved under ignored local `archive/`.
