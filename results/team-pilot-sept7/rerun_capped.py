"""One fresh private wave-one attempt with a larger token budget.

Run using messageboardbench/.venv/bin/python. Never resumes or mutates old runs.
"""
from pathlib import Path
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen

BENCH = Path(__file__).resolve().parents[3] / "messageboardbench"
sys.path.insert(0, str(BENCH / "scripts"))
from team import SnapshotRecorder, archive_sources, configuration, parser
from dotenv import load_dotenv
from inspect_ai import Task, eval as inspect_eval
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log
from inspect_ai.util import SandboxEnvironmentSpec
from messageboardbench.analysis import rows, summarise, write_csv, write_annotation_template
from messageboardbench.shared import prepare_team_directory, render_team_compose, validate_shared_docker
from messageboardbench.task import scratch_solver, scratch_scorer, team_scratch_instructions


def budget():
    request = Request("https://openrouter.ai/api/v1/key", headers={
        "Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]})
    with urlopen(request, timeout=30) as response:
        data = json.load(response)["data"]
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            **{key: data.get(key) for key in ("limit", "limit_remaining", "usage")}}


def main():
    os.chdir(BENCH)
    load_dotenv(BENCH / ".env")
    old_dir = BENCH / "logs/team-conflicting-private-sept7"
    old_path = next((old_dir / "evals").glob("*wave1*.eval"))
    old_log = read_eval_log(old_path)
    old_sample = next(s for s in old_log.samples if s.id == "lcbhard_0")
    assert old_sample.limit.type == "token"
    old_config = json.loads((old_dir / "manifest.json").read_text())
    old_input = next(x for x in json.loads((old_dir / "wave-1-inputs.json").read_text())
                     if x["sample_id"] == old_sample.id)
    assert old_input["metadata"]["scratch_mode"] == "private"
    assert old_input["metadata"]["wave"] == 1
    # Guard the behavior-affecting implementation against accidental prompt/scorer changes.
    for path, expected in old_config["source_sha256"].items():
        if Path(path).name in ("task.py", "livecodebench_scorers.py", "compose.team.yaml"):
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected, path
    out = BENCH / "logs/token-rerun-private-lcbhard-0-sept7"
    args = parser().parse_args(["--condition", "private", "--out", str(out)])
    config = configuration(args)
    config.update(purpose="single-capped-attempt-fresh-rerun", agents=1, waves=1,
                  ids=[old_sample.id], concurrency=1, token_limit=1000000,
                  source_run=str(old_dir), source_eval=str(old_path),
                  source_eval_sha256=hashlib.sha256(old_path.read_bytes()).hexdigest(),
                  previous_token_limit=400000, previous_tokens=409497,
                  fresh_context=True, fresh_empty_private_scratch=True,
                  comparison_caveat="Fresh stochastic attempt; not continuation or a causal estimate.")
    config["source_sha256"][str(Path(__file__).resolve())] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    out.mkdir(parents=True, exist_ok=False)
    (out / "manifest.json").write_text(json.dumps(config, indent=2) + "\n")
    archive_sources(config, out / "source-snapshot")
    before = budget()
    (out / "budget-before.json").write_text(json.dumps(before, indent=2) + "\n")
    print("Budget before:", json.dumps(before), flush=True)
    check = validate_shared_docker(out)
    (out / "infrastructure-check.json").write_text(json.dumps(check, indent=2) + "\n")
    directory = prepare_team_directory(out, "agent-1", ["agent-1"])
    compose = render_team_compose(directory, out / "configs/agent-1.json")
    metadata = dict(old_input["metadata"], team_dir=str(directory))
    assert team_scratch_instructions(metadata) == old_input["scratch_system_instructions"]
    sample = Sample(id=old_sample.id, input=old_sample.input, target=old_sample.target,
                    metadata=metadata, sandbox=SandboxEnvironmentSpec("docker", str(compose)))
    (out / "wave-1-inputs.json").write_text(json.dumps([dict(old_input, metadata=metadata)], indent=2) + "\n")
    task = Task(name="capped_rerun_private_lcbhard_0", dataset=[sample],
                solver=scratch_solver(), scorer=scratch_scorer("conflicting"),
                sandbox=("docker", str(compose)), message_limit=60, metadata=config)
    recorder = SnapshotRecorder({"agent-1": directory}, out / "scratch-history.jsonl")
    with recorder:
        logs = inspect_eval(task, model=old_log.eval.model, log_dir=str(out / "evals"),
                            max_samples=1, max_sandboxes=1, max_connections=1,
                            max_retries=1, timeout=300, retry_on_error=0,
                            time_limit=1800, token_limit=1000000, fail_on_error=False)
    table = rows(s for log in logs for s in (log.samples or []))
    write_csv(table, out / "samples.csv")
    write_annotation_template(table, out / "annotations.csv")
    summary = {**summarise(table), "eval_statuses": [log.status for log in logs],
               "snapshot_error": recorder.error}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    after = budget()
    after["usage_delta"] = after["usage"] - before["usage"]
    (out / "budget-after.json").write_text(json.dumps(after, indent=2) + "\n")
    print(json.dumps({"summary": summary, "budget": after}, indent=2), flush=True)
    if len(table) != 1 or recorder.error or any(log.status != "success" for log in logs):
        raise RuntimeError("Incomplete attempt; inspect preserved evidence before any further run")


if __name__ == "__main__":
    main()
