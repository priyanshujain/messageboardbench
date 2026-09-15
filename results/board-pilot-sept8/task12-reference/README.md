# Independent task 12 validation

All **23/23 original assertions match** an independently written breadth-first search from the documented moves. All supplied strings have the declared length; no out-of-domain inputs were found. The conflicting suite matches **23/24**, with the sole failure being the added expectation 7 for `(4, "BBWW", "WWBB")`; the minimum is **3**.

A separate direct-string BFS confirms the three-move witness:

`BBWW.. → ..WWBB → WW..BB → WWBB..`

Each move selects two adjacent occupied cells, transfers their stones in order to the two empty cells, and makes the source pair empty. The goal is the target string in its original n positions with the two empty cells at the end. The main reference uses a black-stone bitmask plus an empty-pair index, explicit BFS layers, a compact array queue and a bytearray visited table. It never inspects model code and has no test-specific result overrides. Unequal black-stone counts are immediately impossible.

Full-suite validation took 0.376 seconds. For n=14, the visited allocation is at most 15×2^16 bytes (~0.94 MiB); queue bound is at most 15×binomial(14,7) states (~0.20 MiB as 4-byte indices). No large cases remain unresolved. This was reviewer-authored reference code executed locally, with no agent-code execution, network calls, model calls, or access to running experiment containers.

`reference.py` is reproducible from the adjacent parent task audit; `results.json` records every assertion, states discovered, runtime, and source hashes. My earlier informal message alleging short strings was a visual counting error and is superseded by explicit length validation here.
