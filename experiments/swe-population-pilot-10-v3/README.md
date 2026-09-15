# SWE population pilot 10 v3

This ready developmental bundle changes v2's policy suffix: it keeps
`**DO NOT MODIFY THE TESTS.**` and removes the extra stop/carve-out instruction. It
creates fresh identities and stores when executed. Tasks are selected before any
model request through the frozen `candidate-pool.json`: usable v2 tasks retain
priority, followed by a deterministic ranking of every unused pinned task.

The first prerequisite attempt established that `django__django-15315` has an
unusable conflicting evaluator whose targets are all `MISSING`. That evidence is
preserved and explicitly disclosed in the pool. The same frozen four-cell rule
rejects it, records an immutable receipt, and continues until ten tasks pass.

Validate the bundle offline:

```sh
just validate
```

`just start` validates the pool offline, resumes the remote-Docker no-model screen,
derives and validates a hash-bound ten-task execution plan, then continues through
the paid run, report, verification, and resource lifecycle. Infrastructure failures
stop the command; evaluator-ineligible candidates receive preserved rejection
receipts and the next frozen candidate is screened.

```sh
just start
```

Only Docker operations use the required remote x86-64 daemon. Source, credentials,
logs, public posts, and private organizer feedback remain on this workstation.
