# September 8 repository consolidation

`messageboardbench` is now the sole working repository for this experiment.
The old `messageboard` directory was retired to
`../../../archive/messageboard-20260908`; its remaining files and Git history
were preserved, including personal notes, old paper drafts and obsolete code.
Its credentials and environment were not imported into this repository.

Selected moves:

| Original path under messageboard | New path under messageboardbench |
|---|---|
| `scratchpad/board-interface-v2-sept8` | `results/board-interface-v2-sept8` |
| `scratchpad/board-pilot-sept8` | `results/board-pilot-sept8` |
| `scratchpad/model-comparison-sept7` | `results/model-comparison-sept7` |
| `scratchpad/team-pilot-sept7` | `results/team-pilot-sept7` |
| `scratchpad/token-comparison-sept7` | `results/token-comparison-sept7` |
| `scratchpad/sept10-revision` | `results/sept10-revision` |
| `research/09-shared-scratch-design.md` | `docs/research/09-shared-scratch-design.md` |
| `research/10-private-scratch-public-board.md` | `docs/research/10-private-scratch-public-board.md` |
| `research/sources/team-scratch` | `docs/research/sources/team-scratch` |
| `research/sources/board-design-sept7` | `docs/research/sources/board-design-sept7` |

[The manifest](messageboard-20260908.json) lists all 491 retained files, their original
and destination paths, byte counts and SHA-256 hashes. All were verified after
moving. Frozen evidence was not rewritten to hide the move. Given an old absolute
path, strip the manifest's `source_root` and look up `old_path`; `path` is relative
to this repo. Unselected paths map into the retired archive instead.

The current README, workflow docs, EXPERIMENT and AGENTS files supersede historical
plans. The existing upstream `../impossiblebench` dependency remains required;
retiring the research repo does not replace that dependency.

Run `just evidence-check` to verify all migrated bytes. Recompute analyses using
the portable scripts in `scripts/analysis/`, writing into fresh directories rather
than replacing frozen results.
