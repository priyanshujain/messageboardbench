"""Preview or run a small team with a real shared scratchpad and separate task files.

Each wave is a fresh model context. Only scratch files persist between waves.
No seeded workarounds, automatic source publication, or automatic sample retries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--condition", choices=["shared", "private"], default="shared")
    p.add_argument("--split", choices=["original", "conflicting"], default="conflicting")
    p.add_argument("--agents", type=int, choices=[2, 3], default=3)
    p.add_argument("--waves", type=int, choices=[1, 2], default=2)
    p.add_argument("--ids", nargs="+", default=None, help="Distinct task IDs in wave/agent order")
    p.add_argument("--model", default="openrouter/z-ai/glm-5.3-flash")
    p.add_argument("--messages", type=int, choices=[60, 90], default=60)
    p.add_argument("--sample-seconds", type=int, default=1800)
    p.add_argument("--tokens", type=int, default=1000000,
                   help="Per-sample total tokens including repeated input, not a dollar cap")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--check-infrastructure", action="store_true",
                   help="Run Docker sharing/isolation checks only; no model calls")
    return p


def configuration(args: argparse.Namespace) -> dict:
    import messageboardbench.task as task_module
    import messageboardbench.shared as shared_module
    import impossiblebench.livecodebench_scorers as upstream
    n = args.agents * args.waves
    ids = args.ids or ["lcbhard_0", "lcbhard_1", "lcbhard_2", "lcbhard_10", "lcbhard_11", "lcbhard_12"][:n]
    if len(ids) != n or len(set(ids)) != n:
        raise ValueError("Supply one distinct task ID per agent per wave")
    if not 1 <= args.sample_seconds <= 1800 or not 1 <= args.tokens <= 2000000:
        raise ValueError("Use at most 1800 seconds and 2000000 tokens per sample")
    if args.execute and args.check_infrastructure:
        raise ValueError("Choose execution or infrastructure check, not both")
    sources = [Path(__file__), *sorted(Path(task_module.__file__).parent.glob("*.py")),
               Path(upstream.__file__), shared_module.TEAM_COMPOSE]
    return {
        "purpose": "exploratory-team-pilot", "condition": args.condition,
        "split": args.split, "agents": args.agents, "waves": args.waves,
        "ids": ids, "model": args.model, "message_limit": args.messages,
        "time_limit": args.sample_seconds, "token_limit": args.tokens,
        "max_attempts": 3, "concurrency": args.agents, "sample_retries": 0,
        "model_request_retries": 1, "timeout": 300,
        "fresh_context_each_wave": True, "automatic_source_sharing": False,
        "snapshot_interval_seconds": 1,
        "source_sha256": {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
    }


def archive_sources(config: dict, directory: Path) -> None:
    """Keep the exact executed version even while the working tree evolves."""
    directory.mkdir()
    index = []
    for i, (source, expected) in enumerate(config["source_sha256"].items()):
        data = Path(source).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError(f"Source changed during setup: {source}")
        name = f"{i}-{Path(source).name}"
        (directory / name).write_bytes(data)
        index.append({"source": source, "archived": name, "sha256": expected})
    (directory / "index.json").write_text(json.dumps(index, indent=2) + "\n")


class SnapshotRecorder:
    """External, bounded polling audit. Not an atomic per-write filesystem journal."""
    def __init__(self, directories: dict[str, Path], output: Path):
        self.directories = directories
        self.output = output
        self.stop = threading.Event()
        self.error: str | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        from messageboardbench.shared import snapshot_team_directory
        previous = {}
        total = 0
        try:
            with self.output.open("x") as f:
                while True:
                    for name, directory in self.directories.items():
                        snapshot = snapshot_team_directory(directory)
                        if previous.get(name) != snapshot:
                            line = json.dumps({"observed_at": datetime.now(timezone.utc).isoformat(),
                                               "directory": name, "snapshot": snapshot}) + "\n"
                            total += len(line.encode())
                            if total > 50_000_000:
                                raise RuntimeError("External snapshot budget exhausted (50 MB)")
                            f.write(line)
                            f.flush()
                            previous[name] = snapshot
                    if self.stop.wait(1):
                        break
                # Capture the last state after all agent activity has stopped.
                for name, directory in self.directories.items():
                    snapshot = snapshot_team_directory(directory)
                    if previous.get(name) != snapshot:
                        f.write(json.dumps({"observed_at": datetime.now(timezone.utc).isoformat(),
                                            "directory": name, "snapshot": snapshot}) + "\n")
        except Exception as exc:
            self.error = repr(exc)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=15)
        if self.thread.is_alive():
            self.error = "Snapshot collector did not stop within 15 seconds"


def wave_samples(by_id: dict, config: dict, agents: list[str], agent_dirs: dict[str, Path], wave: int) -> list:
    """Fresh sample objects each wave; persistence is exclusively the mounted files."""
    samples = []
    for i, agent in enumerate(agents):
        sample = by_id[config["ids"][wave * len(agents) + i]].model_copy(deep=True)
        sample.metadata = dict(sample.metadata or {})
        sample.metadata.update({"scratch_mode": "team" if config["condition"] == "shared" else "private",
                                "team_id": "team-1", "agent_id": agent, "wave": wave + 1,
                                "team_agents": agents, "team_dir": str(agent_dirs[agent])})
        samples.append(sample)
    return samples


def main() -> None:
    args = parser().parse_args()
    config = configuration(args)
    print(json.dumps(config, indent=2))
    if not args.execute and not args.check_infrastructure:
        print("Preview only; no Docker container or model request started.")
        return
    from messageboardbench.shared import prepare_team_directory, render_team_compose, validate_shared_docker
    # New directory every time: replaying only some members would contaminate team history.
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "manifest.json").write_text(json.dumps(config, indent=2) + "\n")
    archive_sources(config, args.out / "source-snapshot")
    check = validate_shared_docker(args.out)
    (args.out / "infrastructure-check.json").write_text(json.dumps(check, indent=2) + "\n")
    if args.check_infrastructure:
        print(json.dumps(check, indent=2))
        return

    from dotenv import load_dotenv
    from inspect_ai import Task, eval as inspect_eval
    from inspect_ai.util import SandboxEnvironmentSpec
    from messageboardbench.analysis import rows, summarise, write_annotation_template, write_csv
    from messageboardbench.task import scratch_livecodebench, scratch_scorer, scratch_solver, team_scratch_instructions
    load_dotenv()
    base = scratch_livecodebench(split=args.split)
    by_id = {str(sample.id): sample for sample in base.dataset}
    missing = set(config["ids"]) - by_id.keys()
    if missing:
        raise ValueError(f"Unknown task IDs: {sorted(missing)}")
    agents = [f"agent-{i + 1}" for i in range(args.agents)]
    if args.condition == "shared":
        directory = prepare_team_directory(args.out, "team-1", agents)
        agent_dirs = {a: directory for a in agents}
    else:
        agent_dirs = {a: prepare_team_directory(args.out, a, [a]) for a in agents}
    sandbox_configs = {a: render_team_compose(agent_dirs[a], args.out / "configs" / f"{a}.json")
                       for a in agents}
    observed_dirs = {p.name: p for p in agent_dirs.values()}
    table = []
    status = {"completed_waves": 0, "status": "running"}
    recorder = SnapshotRecorder(observed_dirs, args.out / "scratch-history.jsonl")
    try:
        with recorder:
            for wave in range(args.waves):
                samples = wave_samples(by_id, config, agents, agent_dirs, wave)
                for sample in samples:
                    sample.sandbox = SandboxEnvironmentSpec("docker", str(sandbox_configs[sample.metadata["agent_id"]]))
                (args.out / f"wave-{wave + 1}-inputs.json").write_text(json.dumps([
                    {"sample_id": str(s.id), "metadata": s.metadata,
                     "scratch_system_instructions": team_scratch_instructions(s.metadata)} for s in samples
                ], indent=2) + "\n")
                task = Task(name=f"team_lcb_{args.split}_{args.condition}_wave{wave + 1}",
                            dataset=samples, solver=scratch_solver(), scorer=scratch_scorer(args.split),
                            sandbox=("docker", str(sandbox_configs[agents[0]])), message_limit=args.messages,
                            metadata=config)
                logs = inspect_eval(task, model=args.model, log_dir=str(args.out / "evals"),
                                    max_samples=args.agents, max_sandboxes=args.agents,
                                    max_connections=args.agents, max_retries=1, timeout=300,
                                    retry_on_error=0,
                                    time_limit=args.sample_seconds, token_limit=args.tokens,
                                    fail_on_error=False)
                new_rows = rows(s for log in logs for s in (log.samples or []))
                table.extend(new_rows)
                write_csv(table, args.out / "samples.csv")
                if len(new_rows) != args.agents or any(log.status != "success" for log in logs) or any(r["error"] for r in new_rows):
                    raise RuntimeError("Incomplete team wave; inspect logs before a fresh run")
                if recorder.error:
                    raise RuntimeError(f"Scratch audit failed: {recorder.error}")
                status["completed_waves"] = wave + 1
        if recorder.error:
            raise RuntimeError(f"Scratch audit failed: {recorder.error}")
        status["status"] = "completed"
    except BaseException as exc:
        status.update(status="interrupted", error=repr(exc))
        raise
    finally:
        status["snapshot_error"] = recorder.error
        summary = {**status, **summarise(table)}
        (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        write_annotation_template(table, args.out / "annotations.csv")
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
