"""Four paid diagnostics: two models x original/conflicting lcbhard_0.

Uses the original ImpossibleBench tools agent and prompt, with observer-only artifact
capture. No assigned scratchpad or communication channel. Run from the bench venv.
"""
from pathlib import Path
import os, sys, json, hashlib, argparse
from datetime import datetime, timezone
import httpx
from dotenv import load_dotenv
from inspect_ai import Task, eval as inspect_eval
from inspect_ai.scorer import scorer, accuracy
from inspect_ai.util import sandbox
from impossiblebench import impossible_livecodebench
from impossiblebench.livecodebench_scorers import swe_style_humaneval_scorer
import impossiblebench.livecodebench_scorers as upstream
import inspect

HERE = Path(__file__).resolve().parent
BENCH = HERE.parents[2] / "messageboardbench"
OUT = BENCH / "logs/model-comparison-original-prompt-sept7"
MODELS = ["openrouter/meta/muse-spark-1.3-contributor", "openrouter/z-ai/glm-5.3-flash"]


def budget():
    response = httpx.get("https://openrouter.ai/api/v1/key", headers={
        "Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]}, timeout=30)
    response.raise_for_status()
    data = response.json()["data"]
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            **{k: data.get(k) for k in ("usage", "limit", "limit_remaining")}}


@scorer(metrics=[accuracy()])
def observed_scorer():
    inner = swe_style_humaneval_scorer()

    async def score(state, target):
        artifacts = {}
        for path in ("func.py", "test.py"):
            try:
                artifacts[path] = (await sandbox().read_file(path))[:64000]
            except FileNotFoundError:
                artifacts[path] = None
        result = await inner(state, target)
        result.metadata = dict(result.metadata or {})
        modified = result.metadata.get("test_py_was_modified", False)
        state.metadata["observer_test_modified_ever"] = state.metadata.get("observer_test_modified_ever", False) or modified
        result.metadata.update(submitted_artifacts=artifacts,
                               test_modified_ever=state.metadata["observer_test_modified_ever"])
        return result
    return score


def main():
    global OUT
    os.chdir(BENCH)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", choices=MODELS)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--non-strict-tools", action="store_true",
                        help="Provider compatibility: preserve optional tool arguments without strict-schema enforcement")
    args = parser.parse_args()
    models = args.model or MODELS
    OUT = args.out.resolve()
    load_dotenv(BENCH / ".env")
    OUT.mkdir(parents=True, exist_ok=False)
    config = {"purpose": "fresh-original-prompt-model-diagnostic", "models": models,
              "task_ids": ["lcbhard_0"], "splits": ["original", "conflicting"],
              "attempts": 2 * len(models), "message_limit": 60, "token_limit": 1000000,
              "time_limit": 1800, "max_submissions": 3, "reasoning_effort": "high",
              "temperature": 1, "max_retries": 1, "retry_on_error": 0,
              "timeout": 300, "assigned_scratchpad": False, "board": False,
              "extra_integrity_instruction": False,
              "strict_tools": not args.non_strict_tools,
              "scorer_change": "Observer-only pre-grading artifact capture; upstream scoring unchanged.",
              "scope": "One task pair per model; diagnostic, not a model-level rate estimate."}
    source_dir = OUT / "source-snapshot"
    source_dir.mkdir()
    source_paths = [Path(__file__), Path(inspect.getfile(impossible_livecodebench)),
                    Path(upstream.__file__), BENCH / "compose.yaml"]
    # Preserve upstream solver/init sources as well.
    source_paths += sorted(Path(upstream.__file__).parent.glob("*solver*.py"))
    index = []
    for i, path in enumerate(dict.fromkeys(source_paths)):
        data = path.read_bytes(); name = f"{i}-{path.name}"
        (source_dir / name).write_bytes(data)
        index.append({"source": str(path), "archived": name,
                      "sha256": hashlib.sha256(data).hexdigest()})
    config["sources"] = index
    (OUT / "manifest.json").write_text(json.dumps(config, indent=2) + "\n")
    before = budget()
    (OUT / "budget-before.json").write_text(json.dumps(before, indent=2) + "\n")
    print("Budget before:", before, flush=True)
    tasks = []
    for split in config["splits"]:
        base = impossible_livecodebench(split=split, agent_type="tools", sandbox="docker",
                                       message_limit=60, max_attempts=3)
        sample = next(s for s in base.dataset if str(s.id) == "lcbhard_0")
        task = Task(name=f"model_diagnostic_{split}", dataset=[sample], solver=base.solver,
                    scorer=observed_scorer(), sandbox=("docker", str(BENCH / "compose.yaml")),
                    message_limit=60, metadata={**config, "split": split})
        (OUT / f"{split}-input.json").write_text(sample.model_dump_json(indent=2) + "\n")
        tasks.append(task)
    logs = inspect_eval(tasks, model=models, log_dir=str(OUT / "evals"),
                        model_args={"strict_tools": not args.non_strict_tools},
                        max_tasks=4, max_samples=4, max_sandboxes=4, max_connections=4,
                        max_retries=1, timeout=300, retry_on_error=0, fail_on_error=False,
                        time_limit=1800, token_limit=1000000,
                        reasoning_effort="high", temperature=1)
    results = []
    for log in logs:
        for sample in log.samples or []:
            results.append({"model": log.eval.model, "task": log.eval.task,
                            "sample_id": sample.id, "log": log.location,
                            "status": log.status, "score": {k: v.value for k, v in (sample.scores or {}).items()},
                            "messages": len(sample.messages), "limit": sample.limit.model_dump() if sample.limit else None,
                            "error": sample.error.message if sample.error else None,
                            "model_usage": {k: v.model_dump() for k, v in sample.model_usage.items()}})
    (OUT / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    after = budget(); after["usage_delta"] = after["usage"] - before["usage"]
    (OUT / "budget-after.json").write_text(json.dumps(after, indent=2) + "\n")
    print(json.dumps({"results": results, "budget": after}, indent=2), flush=True)
    if len(results) != config["attempts"] or any(r["status"] != "success" or r["error"] for r in results):
        raise RuntimeError("Incomplete diagnostic; inspect preserved evidence. No automatic reruns.")


if __name__ == "__main__":
    main()
