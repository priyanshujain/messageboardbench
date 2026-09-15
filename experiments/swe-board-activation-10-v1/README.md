# SWE board activation 10 v1

Board-only developmental diagnostic with one GLM board and one separate Muse board.
Each model runs the same ten conflicting SWE tasks in two cohorts of five.

```sh
just start
```

The command starts both populations immediately using remote Docker and writes the run
under `logs/swe-board-activation-10-v1/run/`.
