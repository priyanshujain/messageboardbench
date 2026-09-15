---
name: experiment-analysis
description: Analyze a completed messageboardbench experiment, preserve evidence, write the maintained analysis.md in its experiment folder, and commit the associated code and analysis. Use after an experimental run completes or when prior results are reanalyzed.
---

# Experiment Analysis

Produce an evidence-linked interpretation without changing raw run evidence.

1. Read `AGENTS.md`, `EXPERIMENT.md`, and the target experiment's design, plan,
   manifest, status, automatic report, verification, and resource outputs. Resolve
   claims against raw transcripts, tool events, audit records, scorer artifacts,
   and the executed source snapshot when needed.
2. Use independent subagents for statistical/artifact integrity and trajectory or
   communication review. The primary agent checks and integrates their work.
3. Validate assignment counts, matched tasks, missing outcomes, limits, scorer
   execution, tool availability in recorded model requests, report arithmetic,
   lifecycle completion, and source provenance. Treat `MISSING`/`ERROR` target
   statuses and setup failures separately from ordinary behavioral failure.
4. Separate automatic scorer outcomes from reviewed behavioral labels. For shared
   communication, distinguish publication, successful tool delivery, peer receipt,
   attributed adoption, rejection/correction, and independent discovery. Do not
   infer transmission from similar code. Treat organizer-feedback use as a reporting
   proxy until its content and timing are reviewed.
5. Write or update lowercase `analysis.md` inside the target `experiments/<id>/`
   folder. Include design and run identity, data integrity, corrected quantitative
   results, reviewed behavior, communication/feedback evidence, resource use,
   limitations, conclusions, and concrete next decisions. Link repository-relative
   evidence and preserve stale or faulty reports rather than overwriting them; place
   recomputations in a fresh derived location.
6. Run proportionate offline validation. Do not launch paid calls or Docker jobs as
   part of analysis unless the user separately authorizes them.

## Versioning

Before a new experiment launch, prefer a clean code/config commit and record that
identity in the frozen plan or manifest. After an experiment and its analysis are
complete, inspect staged files for secrets and accidental raw logs, run the relevant
offline tests, and commit the experiment code/config/docs/analysis. Report the commit
hash. If code changed during or after execution, state that the executed source
snapshot—not the later commit—is authoritative for the run; never imply otherwise.
