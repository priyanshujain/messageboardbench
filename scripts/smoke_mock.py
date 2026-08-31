"""Free end-to-end smoke test: the real task, a fake model, no money.

Runs the unmodified ImpossibleBench LiveCodeBench task against mockllm/model. The mock
never calls a tool, so it burns the message limit and falls through to the scorer. That
still exercises everything except the model: container start under our compose.yaml, the
writes of func.py and test.py, the scorer's test-file comparison, and `python test.py`.

Run from the repo root so inspect finds compose.yaml (it looks in the process working
directory). scripts/ recipes in the justfile do that for you.
"""

from inspect_ai import eval as inspect_eval
from impossiblebench import impossible_livecodebench

if __name__ == "__main__":
    logs = inspect_eval(
        impossible_livecodebench(
            split="conflicting",
            agent_type="tools",
            sandbox="docker",
            limit=1,
            max_attempts=1,
            message_limit=4,
        ),
        model="mockllm/model",
        log_dir="./logs/smoke",
    )

    log = logs[0]
    print(f"\nstatus: {log.status}")
    if log.error:
        print(f"error: {log.error}")
    for sample in log.samples or []:
        print(f"sample {sample.id}: score={sample.scores}")
        print(f"  working dir sanity: {sample.metadata.get('task_id')}")
