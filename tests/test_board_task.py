import asyncio
from types import SimpleNamespace

import pytest
from inspect_ai.tool import ToolDef

import messageboardbench.task as historical
import messageboardbench.board_task as module


def test_baseline_bytes_and_minimal_prompt_difference(monkeypatch):
    class Sandbox:
        async def write_file(self, *args): pass
        async def exec(self, args): return SimpleNamespace(success=True, stdout="")
    monkeypatch.setattr(historical, "sandbox", Sandbox)
    monkeypatch.setattr(module, "sandbox", Sandbox)
    states = {}
    for condition in ["baseline", "private", "board", "sham", "shared"]:
        state = SimpleNamespace(messages=[], metadata={"instruction_prompt": "TASK"})
        states[condition] = asyncio.run(module.episode_init(condition, "worker-1234")(state, None))
    # Compare against the saved exact original prompt, replacing only task instruction.
    from inspect_ai.log import read_eval_log
    from pathlib import Path
    logs = list((Path(__file__).parents[1]/"logs/model-comparison-original-prompt-sept7/evals").glob("*original*.eval"))
    if logs:
        sample = next(read_eval_log(p).samples[0] for p in logs if read_eval_log(p).samples)
        expected = sample.messages[0].content.replace(sample.metadata['instruction_prompt'], 'TASK')
        assert states['baseline'].messages[0].content == expected
    for condition in ["private", "board", "sham", "shared"]:
        expected = states['baseline'].messages[0].content
        if condition == 'board':
            expected = module.describe_team_tools(expected)
            assert expected.count('read_team_messages:') == 1
        elif condition in {'sham', 'shared'}:
            expected = module.describe_neutral_board_tools(expected)
            assert expected.count('board_read:') == 1
        assert states[condition].messages[0].content == expected + "\n" + module.availability(condition,"worker-1234") + "\n"
    assert module.availability("board", "worker-1234").startswith(module.availability("private", "worker-1234"))
    assert module.availability("sham", "worker-1234") == module.availability("shared", "worker-1234")


def test_neutral_conditions_have_identical_nonleading_interface_text():
    text = module.availability('sham', 'worker-1234') + module.NEUTRAL_BOARD_TOOL_LIST
    assert text == module.availability('shared', 'worker-1234') + module.NEUTRAL_BOARD_TOOL_LIST
    lowered = text.lower()
    for leading in ('team', 'useful', 'finding', 'help', 'catch up', 'earlier task'):
        assert leading not in lowered


def test_fresh_episode_rejects_inherited_files(monkeypatch):
    class Sandbox:
        async def write_file(self, *args): pass
        async def exec(self, args):
            return SimpleNamespace(success=True, stdout="inherited-note" if args[0]=='find' else "")
    monkeypatch.setattr(historical, "sandbox", Sandbox)
    monkeypatch.setattr(module, "sandbox", Sandbox)
    with pytest.raises(RuntimeError, match="not empty"):
        asyncio.run(module.episode_init("private", "worker-1234")(SimpleNamespace(messages=[],metadata={}),None))


def test_rejects_old_identity_metadata():
    with pytest.raises(ValueError, match="Historical"):
        asyncio.run(module.episode_init("board","worker-1234")(SimpleNamespace(metadata={"scratch_mode":"team"}),None))


def test_sham_and_shared_install_identical_board_and_completion_tools(tmp_path, monkeypatch):
    from messageboardbench.board import initialize_board
    captured = []

    def fake_basic_agent(**kwargs):
        captured.append(kwargs)
        return kwargs

    monkeypatch.setattr(module, 'basic_agent_plain_final', fake_basic_agent)
    for condition in ('sham', 'shared'):
        path = initialize_board(tmp_path / f'{condition}.sqlite', f'run-{condition}')
        module.episode_solver(condition, 'worker-1234', 'task-1', f'run-{condition}', path)

    names = [[ToolDef(tool).name for tool in kwargs['tools']] for kwargs in captured]
    assert names[0] == names[1]
    assert names[0][-2:] == ['board_post', 'board_read']
    assert 'report_inconsistency' not in names[0]


def test_legacy_conditions_keep_stock_loop_and_calibration_can_opt_in(monkeypatch):
    calls = []
    monkeypatch.setattr(
        module, 'basic_agent',
        lambda **kwargs: calls.append(('legacy', kwargs)) or 'legacy',
    )
    monkeypatch.setattr(
        module, 'basic_agent_plain_final',
        lambda **kwargs: calls.append(('plain-final', kwargs)) or 'plain-final',
    )
    monkeypatch.setattr(
        module, 'basic_agent_neutral_edge_v2',
        lambda **kwargs: calls.append(('neutral-edge-v2', kwargs)) or 'neutral-edge-v2',
    )
    assert module.episode_solver('private', 'worker-1', 'task-1', 'no-board') == 'legacy'
    assert module.episode_solver(
        'private', 'worker-2', 'task-2', 'no-board', completion_mode='plain-final'
    ) == 'plain-final'
    assert module.episode_solver(
        'private', 'worker-e', 'task-e', 'no-board', completion_mode='neutral-edge-v2'
    ) == 'neutral-edge-v2'
    assert [kind for kind, _ in calls] == ['legacy', 'plain-final', 'neutral-edge-v2']
    with pytest.raises(ValueError, match='completion mode'):
        module.episode_solver(
            'private', 'worker-3', 'task-3', 'no-board', completion_mode='unknown'
        )
