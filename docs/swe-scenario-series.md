# SWE-bench scenario series

This series reuses the baseline's exact 20 `fjzzq2002/impossible_swebench` records at revision `9c2d34f364b7229e8c0ff807c646100bdc18bbb5`, including record hashes, order, and four sequential cohorts of five.

| Scenario | Status | Record |
| --- | --- | --- |
| Isolated baseline | Complete | [Analysis](../experiments/baseline-swebench/analysis.md) |
| Isolated offline control | Prepared | [Design](../experiments/swe-isolated-offline/DESIGN.md) |
| Shared scratchpad | Complete | [Analysis](../experiments/swe-shared-scratch/analysis.md) |
| Shared board | Analyzed; DeepSeek incomplete | [Analysis](../experiments/swe-shared-board/analysis.md) |
| Board and organizer feedback | Complete | [Analysis](../experiments/swe-board-feedback/analysis.md) |
| Board and internet | Prepared | [Design](../experiments/swe-board-internet/DESIGN.md) |
| Board and token awareness | Running under PJ's control | [Design](../experiments/swe-board-token-budget/DESIGN.md) |

Each scenario runs `openrouter/z-ai/glm-5.3-flash`, `openrouter/meta/muse-spark-1.3-contributor`, and `openrouter/deepseek/deepseek-v4-pro-0813`. Each model has independent communication storage and history. The baseline DeepSeek run used ClinePass, so it is not a provider-matched control for the new DeepSeek runs.

The new isolated control, scratchpad, board, feedback, and token-awareness plans set agent networking to `none`. The internet plans use a project-specific bridge. All new scenarios use an offline fresh grader, immutable grader image identity, strict null treatment for missing or error target statuses, a 100-message limit, 1,000,000 metered-token limit, 1,800-second episode limit, 600-second grader limit, ten submissions, and temperature 1.

The scratchpad intervention advertises only `/workspace/scratch`; it does not disclose peer access. Board scenarios use the same optional team prompt and `post_message` and `read_messages` tools. Feedback adds only the private write-only organizer tool. Internet adds only outbound agent network access. Token awareness adds the exact budget sentence and `check_remaining_tokens` tool.

The primary comparisons are scratchpad versus isolated offline, board versus isolated offline, feedback versus board, internet versus board, and token awareness versus board. Scratchpad versus board is descriptive because both the medium and model-visible framing differ.

Three malformed tasks and two satisfiable tasks are outside the valid contradictory-task estimand. Null grader outcomes are infrastructure outcomes rather than behavioral failures. One shared history per model is the propagation inference unit. Publication, exact delivery, attributed adoption, candidate adoption, rejection, and independent discovery remain separate labels.
