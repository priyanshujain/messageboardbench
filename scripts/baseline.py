"""Phase 1: the two numbers that decide whether the study is viable.

Runs the unmodified ImpossibleBench LiveCodeBench task twice over the same 40 tasks.

  conflicting  the tests contradict each other, so no honest solution exists and any pass
               is provably a cheat. This is the cheat rate.
  original     the same 40 tasks unmutated. This is the solve rate, and it answers a
               question the cheat rate alone cannot: whether the model can code at all.
               If it solves nothing here, a low cheat rate means "too weak to do anything"
               rather than "honest", and the design needs rethinking.

Cost is measured against the OpenRouter credits endpoint rather than estimated from token
counts, so the number written down is the number actually spent.

    uv run python scripts/baseline.py              # both splits
    uv run python scripts/baseline.py conflicting  # just one

Run from the repo root; inspect resolves compose.yaml against the working directory.
"""

import os
import sys

import httpx
from dotenv import load_dotenv
from inspect_ai import eval as inspect_eval
from impossiblebench import impossible_livecodebench

MODEL = os.environ.get("MBB_MODEL", "openrouter/z-ai/glm-5.3-flash")
LIMIT = int(os.environ.get("MBB_LIMIT", "40"))
CONCURRENCY = int(os.environ.get("MBB_CONCURRENCY", "12"))

# GLM 5.3 Flash is a reasoning model and single calls legitimately run for minutes,
# so the timeout is generous. It is here to stop one genuinely hung request from
# holding a slot for the length of the run, not to cut short slow thinking.
REQUEST_TIMEOUT = int(os.environ.get("MBB_TIMEOUT", "900"))

# Per-sample wall clock. One baseline sample hung on a single model request for
# 2h15m with no file activity and never came back; the request timeout did not
# bound it. Samples that finish take 8 to 15 minutes, so 30 is generous, and an
# unbounded straggler blocking a whole run is worth more than the sample.
SAMPLE_TIME_LIMIT = int(os.environ.get("MBB_SAMPLE_LIMIT", "1800"))


def credits_used() -> float | None:
    """Total credits spent on the key so far, or None if the endpoint is unavailable."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    try:
        r = httpx.get(
            "https://openrouter.ai/api/v1/credits",
            headers={"Authorization": f"Bearer {key}"},
            timeout=30,
        )
        r.raise_for_status()
        return float(r.json()["data"]["total_usage"])
    except Exception as e:  # noqa: BLE001 - cost reporting must never abort a paid run
        print(f"  (could not read credits: {e})")
        return None


def run_split(split: str) -> dict:
    before = credits_used()
    logs = inspect_eval(
        impossible_livecodebench(
            split=split,
            agent_type="tools",
            sandbox="docker",
            limit=LIMIT,
        ),
        model=MODEL,
        log_dir=f"./logs/baseline/{split}",
        max_connections=CONCURRENCY,
        max_sandboxes=CONCURRENCY,
        max_subprocesses=CONCURRENCY,
        fail_on_error=False,
        timeout=REQUEST_TIMEOUT,
        max_retries=3,
        time_limit=SAMPLE_TIME_LIMIT,
    )
    after = credits_used()
    log = logs[0]

    samples = log.samples or []
    scored = [s for s in samples if s.scores]
    passed = sum(
        1
        for s in scored
        for sc in s.scores.values()
        if str(sc.value).upper() in ("C", "CORRECT", "1", "1.0")
    )
    errored = [s for s in samples if s.error]

    usage = log.stats.model_usage if log.stats else {}
    tok_in = sum(u.input_tokens for u in usage.values())
    tok_out = sum(u.output_tokens for u in usage.values())
    cached = sum((u.input_tokens_cache_read or 0) for u in usage.values())

    n = len(scored) or 1
    return {
        "split": split,
        "status": log.status,
        "samples": len(samples),
        "scored": len(scored),
        "errored": len(errored),
        "passed": passed,
        "rate": passed / n,
        "tok_in": tok_in,
        "tok_out": tok_out,
        "cache_read": cached,
        "cost": (after - before) if (before is not None and after is not None) else None,
        "log": str(log.location),
    }


def report(r: dict) -> None:
    label = "cheat rate" if r["split"] == "conflicting" else "solve rate"
    cost = f"${r['cost']:.4f}" if r["cost"] is not None else "unknown"
    per_run = f"${r['cost'] / max(r['scored'], 1):.5f}" if r["cost"] is not None else "unknown"
    print(f"\n--- {r['split']} ---")
    print(f"  status      {r['status']}  ({r['errored']} errored, {r['scored']} scored)")
    print(f"  {label}  {r['passed']}/{r['scored']} = {r['rate']:.1%}")
    print(f"  tokens      in={r['tok_in']:,} out={r['tok_out']:,} cache_read={r['cache_read']:,}")
    print(f"  cost        {cost} total, {per_run} per run")
    print(f"  log         {r['log']}")


if __name__ == "__main__":
    load_dotenv()
    splits = sys.argv[1:] or ["conflicting", "original"]
    results = [run_split(s) for s in splits]
    print("\n" + "=" * 70)
    for r in results:
        report(r)
