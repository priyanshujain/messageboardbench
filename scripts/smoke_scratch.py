"""Free end-to-end check of the forked task: scratch directory, prompt, snapshot.

Uses mockllm, so it costs nothing and proves everything except the model: the scratch
directory is created before the agent runs, the system prompt names it exactly once, the
scorer snapshots the directory back out, and the inner ImpossibleBench scorer does not
flag test.py as modified (which would mean our construction had drifted from theirs).
"""

from inspect_ai import eval as inspect_eval

from messageboardbench.task import SCRATCH_LINE, scratch_livecodebench

if __name__ == "__main__":
    log = inspect_eval(
        scratch_livecodebench(limit=1, max_attempts=1, message_limit=4),
        model="mockllm/model",
        log_dir="./logs/smoke-scratch",
    )[0]

    print(f"\nstatus: {log.status}")
    assert log.status == "success", log.error

    ok = True
    for sample in log.samples or []:
        system = next(
            (m.text for m in sample.messages if m.role == "system"), ""
        )
        n = system.count(SCRATCH_LINE)
        whole = "\n".join(m.text for m in sample.messages)
        total = whole.count(SCRATCH_LINE)

        score = next(iter(sample.scores.values()))
        meta = score.metadata or {}

        print(f"sample {sample.id}")
        print(f"  scratch line in system message: {n} (want 1)")
        print(f"  scratch line anywhere else:     {total - n} (want 0)")
        print(f"  test flagged as modified:       {meta.get('test_modified_ever')} (want False)")
        print(f"  scratch directory created:      {meta.get('scratch_exists')} (want True)")
        print(f"  scratch snapshot:               {meta.get('scratch_files')}")
        print(f"  score:                          {score.value}")

        ok &= (
            n == 1
            and total == n
            and meta.get("test_modified_ever") is False
            and meta.get("scratch_exists") is True
        )

    print("\nOK" if ok else "\nFAILED")
    raise SystemExit(0 if ok else 1)
