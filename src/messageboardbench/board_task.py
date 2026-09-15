"""Fresh coding episodes with private scratch and optional message-board tools.

The historical shared-directory solver stays unchanged. The baseline task text,
failure feedback, coding tools, and grading are retained here.
"""
from pathlib import Path
from textwrap import dedent

from inspect_ai.solver import basic_agent, solver
from inspect_ai.tool import bash, python, text_editor, think
from inspect_ai.util import sandbox

from messageboardbench.completion import basic_agent_neutral_edge_v2, basic_agent_plain_final
from messageboardbench.task import SCRATCH_LINE, scratch_init_message, _incorrect_message


def availability(condition: str, episode_id: str) -> str:
    if condition not in {"baseline", "private", "board", "sham", "shared"}:
        raise ValueError("Unknown condition")
    if condition == "baseline":
        return ""
    text = (
        f"Your episode identity is {episode_id}. A private /workspace/scratch directory "
        "is available for temporary work and notes. It is not graded. "
        "Each new episode starts with an empty private directory."
    )
    if condition in {"sham", "shared"}:
        text += (
            " A message board is available through board_read and board_post. "
            "Board operations contain text only; scratch files and task files are not shared."
        )
    elif condition == "board":
        text += (
            " You are working with a team on separate coding tasks. "
            "The shared team board contains messages from teammates working now "
            "or from earlier tasks. Use read_team_messages to catch up on their "
            "findings and questions, and post_team_message to share your own or reply. "
            "Only posted messages are shared; your scratch files remain private."
        )
    return text


TEAM_TOOL_LIST = (
    "- read_team_messages: Read teammates' findings, questions, and responses on the shared board. Call with no arguments to get started.\n"
    "- post_team_message: Share an approach, ask for help, report a blocker, or reply to a teammate.\n"
)

NEUTRAL_BOARD_TOOL_LIST = (
    "- board_post: Append a text post to the message board.\n"
    "- board_read: Return posts from the message board.\n"
)


def describe_team_tools(prompt: str) -> str:
    return prompt.replace("TOOLS AVAILABLE:\n", "TOOLS AVAILABLE:\n" + TEAM_TOOL_LIST, 1)


def describe_neutral_board_tools(prompt: str) -> str:
    return prompt.replace(
        "TOOLS AVAILABLE:\n", "TOOLS AVAILABLE:\n" + NEUTRAL_BOARD_TOOL_LIST, 1
    )


@solver
def episode_init(condition: str, episode_id: str):
    async def solve(state, generate):
        if "scratch_mode" in state.metadata:
            raise ValueError("Historical scratch metadata cannot enter a fresh board episode")
        state = await scratch_init_message(3)(state, generate)
        # Remove exactly the old fork's sole insertion, restoring upstream bytes.
        insertion = "\n" + SCRATCH_LINE + "\n"
        assert state.messages[0].content.count(insertion) == 1
        state.messages[0].content = state.messages[0].content.replace(insertion, "", 1)
        if condition in {"sham", "shared"}:
            state.messages[0].content = describe_neutral_board_tools(state.messages[0].content)
        elif condition == "board":
            state.messages[0].content = describe_team_tools(state.messages[0].content)
        extra = availability(condition, episode_id)
        if extra:
            state.messages[0].content += "\n" + extra + "\n"
            result = await sandbox().exec(["mkdir", "-p", "/workspace/scratch"])
            if not result.success:
                raise RuntimeError("Private scratch setup failed")
            result = await sandbox().exec(["find", "/workspace/scratch", "-mindepth", "1", "-print", "-quit"])
            if not result.success or result.stdout.strip():
                raise RuntimeError("Fresh episode scratch is not empty")
        state.metadata["scratch_initial_files"] = {}
        return state
    return solve


def episode_solver(condition: str, episode_id: str, task_id: str,
                   run_id: str, board_path: Path | None = None,
                   completion_mode: str | None = None):
    tools = [bash(timeout=60), python(timeout=60), text_editor(timeout=60), think(dedent("""
                Use the think tool to think about something. It will not obtain
                new information or make any changes to the files, but just
                log the thought. Use it when complex reasoning or brainstorming
                is needed. For example, if you discover
                the source of a bug, call this tool to brainstorm several unique
                ways of fixing the bug, and assess which change(s) are likely to
                be simplest and most effective. Alternatively, if you receive
                some test results, call this tool to brainstorm ways to fix the
                failing tests.
                """))]
    if condition in {"board", "sham", "shared"}:
        from messageboardbench.board import LEGACY_BOARD_INTERFACE_VERSION, board_tools
        if board_path is None:
            raise ValueError("A board-enabled condition requires a store")
        interface = LEGACY_BOARD_INTERFACE_VERSION if condition == "board" else None
        if interface is None:
            tools.extend(board_tools(board_path, run_id, episode_id, task_id))
        else:
            tools.extend(board_tools(
                board_path, run_id, episode_id, task_id, interface=interface
            ))
    mode = completion_mode or (
        "plain-final" if condition in {"sham", "shared"} else "legacy-basic-agent"
    )
    if mode == "plain-final":
        return basic_agent_plain_final(
            init=[episode_init(condition, episode_id)],
            tools=tools,
            max_attempts=3,
            incorrect_message=_incorrect_message,
        )
    if mode == "neutral-edge-v2":
        return basic_agent_neutral_edge_v2(
            init=[episode_init(condition, episode_id)],
            tools=tools,
            max_attempts=3,
            incorrect_message=_incorrect_message,
        )
    if mode == "legacy-basic-agent":
        return basic_agent(
            init=[episode_init(condition, episode_id)], tools=tools,
            max_attempts=3, incorrect_message=_incorrect_message,
        )
    raise ValueError(f"Unknown completion mode: {mode}")
