from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from inspect_ai.model import ModelOutput
from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.solver import TaskState, basic_agent, solver
from inspect_ai.tool import ToolDef, tool

from messageboardbench.completion import (
    MAX_EXPLANATION_CHARACTERS,
    REPORT_TOOL_NAME,
    REASONING_ONLY_CONTINUATION,
    basic_agent_neutral_edge_v2,
    basic_agent_plain_final,
    completion_manifest_record,
    completion_manifest_record_v2,
    tools_with_inconsistency_report,
)


def _state() -> SimpleNamespace:
    return SimpleNamespace(tools=[], metadata={}, completed=False)


def test_report_tool_ends_without_recording_a_pass() -> None:
    state = _state()
    solved = asyncio.run(tools_with_inconsistency_report([])(state, None))
    assert len(solved.tools) == 1
    report = solved.tools[-1]
    result = asyncio.run(report(explanation="The same input requires 3 and 7."))
    assert "without a passing claim" in result
    assert state.completed is True
    assert state.metadata["unsuccessful_completion"] == {
        "kind": "claimed_test_inconsistency",
        "explanation": "The same input requires 3 and 7.",
        "requires_review": True,
        "counts_as_passing": False,
    }


def test_report_rejects_empty_or_oversized_explanations() -> None:
    state = _state()
    solved = asyncio.run(tools_with_inconsistency_report([])(state, None))
    assert len(solved.tools) == 1
    report = solved.tools[-1]
    with pytest.raises(ValueError, match="required"):
        asyncio.run(report(explanation="  "))
    with pytest.raises(ValueError, match="exceeds"):
        asyncio.run(report(explanation="x" * (MAX_EXPLANATION_CHARACTERS + 1)))
    assert state.completed is False
    assert state.metadata == {}


def test_legacy_report_retains_existing_tools() -> None:
    async def existing() -> str:
        return "ok"

    existing.name = "existing"  # type: ignore[attr-defined]
    state = _state()
    state.tools = [existing]
    solved = asyncio.run(tools_with_inconsistency_report([])(state, None))
    assert solved.tools[0] is existing
    assert ToolDef(solved.tools[-1]).name == REPORT_TOOL_NAME


def test_plain_final_terminates_without_adding_a_visible_completion_tool() -> None:
    @solver
    def init():
        async def solve(state, generate):
            return state
        return solve

    @tool
    def existing():
        async def execute(value: str) -> str:
            """Use an ordinary test tool.

            Args:
                value: Arbitrary value.
            """
            return value
        return execute

    state = TaskState(
        model="mock/test", sample_id="sample", epoch=1, input="task",
        messages=[], metadata={},
    )

    async def generate(state, tool_calls):
        assert tool_calls == "single"
        state.output = ModelOutput.from_content(
            "mock/test", "The evaluator cannot be satisfied as written."
        )
        state.messages.append(state.output.message)
        return state

    result = asyncio.run(basic_agent_plain_final(
        init=init(), tools=[existing()], max_attempts=3, incorrect_message="try again"
    )(state, generate))
    assert result.completed is True
    assert result.metadata["plain_text_completion"] == {
        "text": "The evaluator cannot be satisfied as written.",
        "requires_review": True,
        "artifact_scored_normally": True,
    }
    assert [ToolDef(value).name for value in result.tools] == ["existing", "submit"]
    assert REPORT_TOOL_NAME not in [ToolDef(value).name for value in result.tools]


def test_new_completion_manifest_is_neutral_and_model_invisible() -> None:
    record = completion_manifest_record()
    assert record["mode"] == "plain-assistant-final-or-submit"
    assert record["adds_model_visible_tools"] is False
    assert record["adds_model_visible_wording"] is False
    assert record["artifact_scored_normally"] is True
    assert record["installed_identically_across_conditions"] is True
    assert REPORT_TOOL_NAME not in str(record)


def test_v2_substantive_visible_final_terminates_without_rescue() -> None:
    @solver
    def init():
        async def solve(state, generate): return state
        return solve
    state = TaskState(model="mock/test", sample_id="x", epoch=1, input="task",
                      messages=[], metadata={})
    calls = 0
    async def generate(state, tool_calls):
        nonlocal calls
        calls += 1
        state.output = ModelOutput.from_content("mock/test", "  final answer  ")
        state.messages.append(state.output.message)
        return state
    result = asyncio.run(basic_agent_neutral_edge_v2(
        init=init(), tools=[], max_attempts=3, incorrect_message="try again"
    )(state, generate))
    assert calls == 1
    assert result.metadata["plain_text_completion"]["text"] == "  final answer  "
    assert "completion_edge_events" not in result.metadata


def test_v2_reasoning_only_gets_exactly_one_rescue_then_visible_final() -> None:
    @solver
    def init():
        async def solve(state, generate): return state
        return solve
    state = TaskState(model="mock/test", sample_id="x", epoch=1, input="task",
                      messages=[], metadata={})
    outputs = [
        [ContentReasoning(reasoning="hidden")],
        [ContentReasoning(reasoning="more hidden"), ContentText(text="done")],
    ]
    async def generate(state, tool_calls):
        state.output = ModelOutput.from_content("mock/test", outputs.pop(0))
        state.messages.append(state.output.message)
        return state
    result = asyncio.run(basic_agent_neutral_edge_v2(
        init=init(), tools=[], max_attempts=3, incorrect_message="try again"
    )(state, generate))
    assert outputs == []
    assert result.messages[1].role == "user"
    assert result.messages[1].text == REASONING_ONLY_CONTINUATION
    assert result.metadata["plain_text_completion"]["text"] == "done"
    assert [event["kind"] for event in result.metadata["completion_edge_events"]] == [
        "empty_visible_no_tool_rescue"
    ]


def test_v2_two_empty_visible_turns_stop_after_one_rescue() -> None:
    @solver
    def init():
        async def solve(state, generate): return state
        return solve
    state = TaskState(model="mock/test", sample_id="x", epoch=1, input="task",
                      messages=[], metadata={})
    calls = 0
    async def generate(state, tool_calls):
        nonlocal calls
        calls += 1
        state.output = ModelOutput.from_content(
            "mock/test", [ContentReasoning(reasoning=f"hidden-{calls}")]
        )
        state.messages.append(state.output.message)
        return state
    result = asyncio.run(basic_agent_neutral_edge_v2(
        init=init(), tools=[], max_attempts=3, incorrect_message="try again"
    )(state, generate))
    assert calls == 2
    assert sum(message.role == "user" for message in result.messages) == 1
    assert result.metadata["plain_text_completion"]["empty_visible_after_rescue"] is True
    assert [event["kind"] for event in result.metadata["completion_edge_events"]] == [
        "empty_visible_no_tool_rescue", "empty_visible_no_tool_termination"
    ]


def test_v2_manifest_discloses_conditional_visible_wording() -> None:
    record = completion_manifest_record_v2()
    assert record["mode"] == "neutral-edge-v2"
    assert record["adds_model_visible_initial_wording"] is False
    assert record["adds_model_visible_edge_continuation"] is True
    assert record["empty_visible_no_tool_rescue_limit"] == 1
    assert record["empty_visible_no_tool_rescue_text"] == REASONING_ONLY_CONTINUATION


def test_submit_tool_schema_matches_stock_basic_agent(monkeypatch) -> None:
    @solver
    def init():
        async def solve(state, generate):
            return state
        return solve

    captured = []

    class StockModel:
        async def generate(self, *, input, tools, cache):
            captured.append(ToolDef(tools[-1]))
            return ModelOutput.from_content(
                "mock/test", "done", stop_reason="model_length"
            )

    import inspect_ai.solver._basic_agent as stock_module
    monkeypatch.setattr(stock_module, "get_model", lambda: StockModel())

    async def generate(state, tool_calls):
        captured.append(ToolDef(state.tools[-1]))
        state.output = ModelOutput.from_content(
            "mock/test", "done", stop_reason="model_length"
        )
        state.messages.append(state.output.message)
        return state

    def state():
        return TaskState(
            model="mock/test", sample_id="sample", epoch=1, input="task",
            messages=[], metadata={},
        )

    asyncio.run(basic_agent(
        init=init(), tools=[], max_attempts=3, incorrect_message="try again"
    )(state(), generate))
    asyncio.run(basic_agent_plain_final(
        init=init(), tools=[], max_attempts=3, incorrect_message="try again"
    )(state(), generate))
    asyncio.run(basic_agent_neutral_edge_v2(
        init=init(), tools=[], max_attempts=3, incorrect_message="try again"
    )(state(), generate))
    stock, neutral_v1, neutral_v2 = captured
    for candidate in (neutral_v1, neutral_v2):
        for field in ("name", "description", "parameters", "parallel", "max_output"):
            assert getattr(candidate, field) == getattr(stock, field)


def test_v2_model_length_neither_rescues_nor_records_plain_final() -> None:
    @solver
    def init():
        async def solve(state, generate): return state
        return solve
    state = TaskState(model="mock/test", sample_id="x", epoch=1, input="task",
                      messages=[], metadata={})
    calls = 0
    async def generate(state, tool_calls):
        nonlocal calls
        calls += 1
        state.output = ModelOutput.from_content(
            "mock/test", [ContentReasoning(reasoning="truncated")],
            stop_reason="model_length",
        )
        state.messages.append(state.output.message)
        return state
    result = asyncio.run(basic_agent_neutral_edge_v2(
        init=init(), tools=[], max_attempts=3, incorrect_message="try again"
    )(state, generate))
    assert calls == 1
    assert "plain_text_completion" not in result.metadata
    assert "completion_edge_events" not in result.metadata
