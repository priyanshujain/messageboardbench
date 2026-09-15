# SWE population pilot 10 v1

This is a 10-problem engineering and signal pilot for the frozen SWE population
experiment. It runs the same ten official ImpossibleBench conflicting tasks once in
control and once with the shared board: 20 paid episodes total.

Start the complete unattended lifecycle from this directory:

```sh
just start
```

The command keeps source, API execution, credentials, logs, boards, and reports on
this workstation. Docker operations alone use `ssh://pj@100.68.126.75`. It resumes
terminal episodes after interruption and automatically writes the deterministic
report, verification, and resource summaries under
`logs/swe-population-pilot-10-v1/`.

To check the frozen configuration without Docker or paid model calls:

```sh
just validate
```

This pilot does not modify or consume `experiments/population-propensity-v1`. Its
single board is useful for exposing execution problems and seeing whether agents post,
read, and game evaluators, but it is not powered for population-level inference.
