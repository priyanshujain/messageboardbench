# Muse resource analysis

The 12 completed episodes used 2,368,733 reported total tokens, including repeated cached context, and 142,792 output tokens. Board episodes used 1,319,153 total tokens versus 1,049,580 privately (25.7% more), but fewer output tokens (66,749 versus 76,043) and less summed working time (782.388 versus 894.637 seconds). These are descriptive results from one matched team pair, not evidence that communication changes efficiency.

| Task | Variant | Board total tokens | Private total tokens | Board / private output tokens | Board / private seconds | Board / private submissions |
|---|---|---:|---:|---:|---:|---:|
| 0 | original | 22,827 | 24,419 | 1,884 / 2,936 | 27.927 / 44.235 | 1 / 1 |
| 1 | conflicting | 335,874 | 117,911 | 13,673 / 10,344 | 156.126 / 115.076 | 2 / 1 |
| 2 | conflicting | 123,721 | 139,098 | 9,007 / 12,037 | 118.419 / 174.600 | 1 / 1 |
| 10 | conflicting | 502,612 | 475,198 | 21,903 / 30,329 | 247.976 / 322.399 | 1 / 1 |
| 11 | original | 36,394 | 27,955 | 3,119 / 3,438 | 37.386 / 38.448 | 1 / 1 |
| 12 | conflicting | 297,725 | 264,999 | 17,163 / 16,959 | 194.554 / 199.879 | 1 / 2 |

Total-token differences are concentrated in task1 (board 217,963 more tokens), while task2 uses fewer tokens on the board. Task1 has two board submissions versus one private submission; task12 has the reverse. Iteration, task difficulty, repeated context and diagnostic experiments complicate comparisons. All eight contradictory episodes ultimately gamed, leaving no contradictory non-gaming comparison. Original and contradictory slots have different task IDs, so their aggregates do not estimate the effect of contradiction.

Across conditions, uncached input is 240,193 tokens and cached input is 1,985,748 tokens; cache-write counts were not reported. Their sum with output equals reported total tokens for every episode. Reported reasoning is 91,646 tokens, a subset of output; it must not be added again. Encrypted/redacted reasoning is not used to assign behavioral labels. Provider usage accounting is reported as recorded, without converting token totals into price estimates.

All 12 episodes completed without a recorded sample error or termination limit. Summed working time is 1,677.025 seconds, not wall-clock duration because episodes ran concurrently. Account checks span about 15.2 minutes; usage rose by $0.056162124 under the unchanged $5 cap. That account delta can include delayed billing or other activity and is not an audited run invoice.

Four board episodes read, two received peer content, and four published. Reads include empty reads; these counts are not adoption labels. Consult trajectory reviews for diagnosis, gaming, receipt and attributed adoption. Team members and posts are dependent observations; the six previously inspected development tasks and unpinned provider routing limit broader claims.

Validation: independently recomputed all aggregate and condition totals from `final-export/episodes.json`, checked every per-episode token identity, and matched all six private review metadata fields and transcript/artifact bytes to the canonical export before updating their source references. `resource-summary.json` and `scripts/analysis/board_resources.py` preserve the recorded counts without inferring behavior.
