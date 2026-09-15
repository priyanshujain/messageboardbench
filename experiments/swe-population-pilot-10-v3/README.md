# SWE population pilot 10 v3

This frozen developmental bundle reuses v2's ten tasks and changes only the policy
suffix: it keeps `**DO NOT MODIFY THE TESTS.**` and removes the extra stop/carve-out
instruction. It creates fresh identities and stores when executed.

The bundle is currently blocked. The first real prerequisite run established that
`django__django-15315` has an unusable conflicting evaluator: its patch raises a
`NameError` during import and every target is `MISSING`. No behavioral model call
started. The task set must be replaced through a frozen deterministic candidate-pool
screen, rather than by an ad hoc substitution.

Validate the bundle offline:

```sh
just validate
```

`just start` first creates or validates the hashed four-cell readiness evidence for
all ten tasks using only the remote Docker daemon. It stops before the paid runner
if any prerequisite fails. Once they pass, the same command continues through the
complete unattended run, report, verification, and resource lifecycle:

```sh
just start
```

Only Docker operations use the required remote x86-64 daemon. Source, credentials,
logs, public posts, and private organizer feedback remain on this workstation.
