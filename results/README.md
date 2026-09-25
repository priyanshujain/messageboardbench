# Experiment evidence

Start with [EXPERIMENT.md](../EXPERIMENT.md). These dated bundles preserve completed
analyses and supporting artifacts; they are not alternative current plans.

| Bundle | Use |
|---|---|
| [board-muse-sept8](board-muse-sept8/RESULTS.md) | Full matched Muse Contributor replication: one attributed adoption, one possible unattributed adoption; all eight gaming artifacts validated. |
| [board-interface-v2-sept8](board-interface-v2-sept8/RESULTS.md) | Latest matched GLM pilot: one attributed cross-task adoption after peer receipt. |
| [board-pilot-sept8](board-pilot-sept8/RESULTS.md) | Prior interface: publication but zero board reads; task validation and SWE readiness. |
| [model-comparison-sept7](model-comparison-sept7/RESULTS.md) | Tiny GLM/Muse Contributor feasibility comparison, not model-level rates. |
| [token-comparison-sept7](token-comparison-sept7/REPORT.md) | Frozen historical token audit and recovered baseline accounting. |
| [team-pilot-sept7](team-pilot-sept7/RESULTS.md) | Historical shared-directory experiment with different prompts and limits. |
| [sept10-revision](sept10-revision/baseline-audit.json) | Historical baseline audit supporting the revision. |

Historical raw Inspect runs are preserved locally in ignored `../archive/logs/`.
Current SWE run logs live in tracked `../logs/`. Migrated reports, reviews, probe
outputs and exports are byte-preserved. Embedded absolute paths
record their original locations; resolve them with
[the migration map](../docs/migration/messageboard-20260908.json). Historical
scripts inside bundles are evidence, not the current run entry points. Use
`just board`, `scripts/board_report.py`, or the portable offline tools in
`scripts/analysis/` for new work, always with a fresh output directory.
