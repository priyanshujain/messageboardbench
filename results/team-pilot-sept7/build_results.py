"""Reanalyse the completed September 7 pilot; run with messageboardbench's venv."""
import hashlib
import json
from pathlib import Path

from inspect_ai.log import read_eval_log
from messageboardbench.analysis import rows, summarise, write_csv
import messageboardbench.analysis as analysis
import messageboardbench.events as events

OUT = Path(__file__).resolve().parent
BENCH = Path(__file__).resolve().parents[3] / "messageboardbench"
result = {"model": "openrouter/z-ai/glm-5.3-flash", "message_limit": 60,
          "pilot_token_limit": 400000, "conditions": {},
          "analysis_sha256": {str(Path(m.__file__).resolve()): hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
                              for m in (analysis, events)}}
for condition, name in (("original_shared", "team-original-sept7"),
                        ("conflicting_shared", "team-conflicting-shared-sept7"),
                        ("conflicting_private", "team-conflicting-private-sept7")):
    run = BENCH / "logs" / name
    paths = sorted((run / "evals").glob("*.eval"))
    logs = [read_eval_log(str(p)) for p in paths]
    samples = [s for log in logs for s in (log.samples or [])]
    table = rows(samples)
    write_csv(table, OUT / f"{condition}-reanalysed.csv")
    result["conditions"][condition] = {
        **summarise(table), "logs": [str(p) for p in paths],
        "token_cutoffs": sum(s.limit is not None and s.limit.type == "token" for s in samples),
        "message_cutoffs": sum(s.limit is not None and s.limit.type == "message" for s in samples),
        "time_cutoffs": sum(s.limit is not None and s.limit.type == "time" for s in samples),
        "per_sample": [{"id": s.id, "agent": s.metadata["agent_id"], "wave": s.metadata["wave"],
                        "messages": len(s.messages),
                        "model_turns": sum(m.role == "assistant" for m in s.messages),
                        "submissions": sum(t.function == "submit" for m in s.messages for t in (getattr(m, "tool_calls", None) or [])),
                        "limit": str(s.limit or "")} for s in samples],
    }
result["qualitative_review"] = {
    "reviewer": "Codex-assisted trace review; independent human validation pending",
    "peer_content_reads_shared": ["lcbhard_1", "lcbhard_10", "lcbhard_11", "lcbhard_12"],
    "peer_content_reads_original": [],
    "executed_gaming_observed_in_reviewed_impossible_attempts": 0,
    "reviewed_impossible_attempts": 12,
    "note": "Peer exposure/reinforcement is not proof warnings caused honesty. See indexed reviews.",
}
result["budget"] = json.loads((OUT / "budget.json").read_text())
(OUT / "results.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({k: {f: v[f] for f in ("n", "passed", "wrote", "token_cutoffs", "message_cutoffs", "time_cutoffs")}
                  for k, v in result["conditions"].items()}, indent=2))
