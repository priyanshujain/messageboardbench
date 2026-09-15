# SWE population pilot 10 v2

This is a fresh 10-problem matched pilot using the next deterministic ten official
ImpossibleBench conflicting SWE tasks after pilot v1. The same tasks run once in
control and once in the communication arm: 20 paid episodes total.

Run the complete unattended, resumable lifecycle from this directory:

```sh
just start
```

The command keeps source, API execution, credentials, logs, feedback, and results on
this workstation. Docker operations alone use `ssh://pj@100.68.126.75`; the repository
is never copied there. After execution it automatically produces the report,
verification, resource summary, exact public-board evidence, and exact private
organizer-feedback evidence under `logs/swe-population-pilot-10-v2/`.

Offline validation, without Docker or paid model calls:

```sh
just validate
```

This one-board pilot checks whether the communication interface activates and gives
a descriptive signal. It is not powered for population-level causal inference.
