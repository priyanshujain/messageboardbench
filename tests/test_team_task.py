import asyncio
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest
from inspect_ai.dataset import Sample

import messageboardbench.task as module

script = runpy.run_path(str(Path(__file__).parents[1] / "scripts" / "team.py"))


def metadata(mode="team"):
    return {"scratch_mode": mode, "agent_id": "agent-1", "team_agents": ["agent-1", "agent-2"]}


def test_shared_setup_fails_if_mount_is_missing(monkeypatch):
    class Sandbox:
        async def exec(self, cmd):
            return SimpleNamespace(success=False)
    monkeypatch.setattr(module, "sandbox", Sandbox)
    state = SimpleNamespace(metadata=metadata())
    with pytest.raises(RuntimeError, match="mount"):
        asyncio.run(module.create_scratch()(state, None))


def test_prompt_is_truthful_and_integrity_instruction_matches():
    team = module.team_scratch_instructions(metadata())
    private = module.team_scratch_instructions(metadata("private"))
    assert "teammates can read and edit" in team
    assert "other agents cannot read or edit" in private
    assert "not automatically shared" in team
    assert "agents/agent-1" in team and "agents/agent-1" in private
    assert team.split("Notes are fallible")[1] == private.split("Notes are fallible")[1]


def test_team_runner_budget_and_no_seed():
    args = script["parser"]().parse_args(["--out", "logs/preview"])
    config = script["configuration"](args)
    assert not args.execute
    assert config["message_limit"] == 60
    assert config["token_limit"] == 1000000
    assert len(config["ids"]) == 6
    assert not config["automatic_source_sharing"]


def test_wave_contexts_are_fresh_and_shared_path_persists(tmp_path):
    agents = ["agent-1", "agent-2"]
    source = {str(i): Sample(id=str(i), input=f"task {i}", metadata={"original": True}) for i in range(4)}
    config = {"ids": list(source), "condition": "shared"}
    paths = {a: tmp_path / "team" for a in agents}
    first = script["wave_samples"](source, config, agents, paths, 0)
    second = script["wave_samples"](source, config, agents, paths, 1)
    assert first[0].metadata["team_dir"] == second[1].metadata["team_dir"]
    assert first[0].input == "task 0" and second[0].input == "task 2"
    assert source["0"].metadata == {"original": True}
    config["condition"] = "private"
    paths = {a: tmp_path / a for a in agents}
    private = script["wave_samples"](source, config, agents, paths, 0)
    assert private[0].metadata["team_dir"] != private[1].metadata["team_dir"]
    assert private[0].metadata["scratch_mode"] == "private"


def test_runner_rejects_ambiguous_task_assignment():
    args = script["parser"]().parse_args(["--out", "logs/preview", "--ids", "lcbhard_0"])
    with pytest.raises(ValueError, match="distinct"):
        script["configuration"](args)


def test_archive_refuses_changed_source(tmp_path):
    import hashlib
    source = tmp_path / "runner.py"
    source.write_text("# original\n")
    config = {"source_sha256": {str(source): hashlib.sha256(source.read_bytes()).hexdigest()}}
    script["archive_sources"](config, tmp_path / "archive")
    assert (tmp_path / "archive" / "0-runner.py").read_bytes() == source.read_bytes()
    source.write_text("# edited\n")
    with pytest.raises(RuntimeError, match="Source changed"):
        script["archive_sources"](config, tmp_path / "changed-archive")
