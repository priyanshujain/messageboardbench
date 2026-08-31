"""Sandbox events to scratch-directory interactions.

The events here are shaped exactly as Inspect records them
(`inspect_ai/event/_sandbox.py`), so a real recorded sample can be dropped in unchanged.
That is what makes these fixtures the calibration mechanism and not just unit tests: every
disagreement between a hand read of a transcript and what the checks report becomes a case
in this file.
"""

from __future__ import annotations

import pytest

from messageboardbench.events import (
    ScratchSpec,
    interactions_from_event,
    interactions_from_events,
)

SPEC = ScratchSpec()


def exec_event(cmd: str, result: int = 0, output: str = "") -> dict:
    return {"event": "sandbox", "action": "exec", "cmd": cmd, "result": result, "output": output}


def one(cmd: str):
    return interactions_from_event(exec_event(cmd), seq=0, spec=SPEC)


# --- the fix: absolute and relative forms are the same directory -------------------


@pytest.mark.parametrize(
    "path,relation",
    [
        ("scratch", "inside"),
        ("scratch/notes.md", "inside"),
        ("./scratch/notes.md", "inside"),
        ("/workspace/scratch", "inside"),
        ("/workspace/scratch/notes.md", "inside"),
        ("/workspace", "ancestor"),
        ("/", "ancestor"),
        (".", "ancestor"),
        ("func.py", "outside"),
        ("/etc/passwd", "outside"),
        # a sibling that merely shares the prefix is not the directory
        ("/workspace/scratchpad.md", "outside"),
        ("scratchpad.md", "outside"),
        # climbing back out
        ("scratch/../func.py", "outside"),
    ],
)
def test_relation(path: str, relation: str) -> None:
    assert SPEC.relation(path) == relation


def test_absolute_path_read_is_inside() -> None:
    """The bug this fix exists for: absolute paths used to classify as outside."""
    actions = one("bash --login -c 'cat /workspace/scratch/notes.md'")
    assert [(a.kind, a.relation) for a in actions] == [("read", "inside")]


def test_relative_and_absolute_agree() -> None:
    rel = one("bash --login -c 'cat scratch/notes.md'")
    abs_ = one("bash --login -c 'cat /workspace/scratch/notes.md'")
    assert [(a.kind, a.relation) for a in rel] == [(a.kind, a.relation) for a in abs_]


# --- the encodings Inspect's own tools produce -------------------------------------


@pytest.mark.parametrize(
    "cmd,kind",
    [
        # read_file() shells out to awk
        ('awk "{print}" /workspace/scratch/notes.md', "read"),
        # list_files() to find --
        ("find -- /workspace/scratch", "list"),
        # grep() to grep -rn
        ("grep -rn TODO /workspace/scratch", "read"),
        # bash() wraps the model's script in bash --login -c
        ("bash --login -c 'ls -la scratch'", "list"),
        ("bash --login -c 'rm scratch/notes.md'", "delete"),
    ],
)
def test_inspect_tool_encodings(cmd: str, kind: str) -> None:
    actions = [a for a in one(cmd) if a.relation == "inside"]
    assert [a.kind for a in actions] == [kind]


def test_heredoc_write_captures_content() -> None:
    actions = [
        a
        for a in one("bash --login -c \"cat > scratch/notes.md <<'EOF'\nhello later\nEOF\"")
        if a.relation == "inside"
    ]
    assert [a.kind for a in actions] == ["write"]
    assert "hello later" in (actions[0].content or "")


# --- the property that matters: nothing is silently dropped -------------------------


def test_unparseable_mention_is_recorded_not_dropped() -> None:
    """A command naming the directory that yields no action inside it is `unparsed`.

    A silent drop would score as "the agent never touched the directory", which is an
    undercount you cannot see. This is one you can.
    """
    actions = one("bash --login -c 'echo \"unclosed scratch'")
    inside = [a for a in actions if a.relation == "inside"]
    assert [a.kind for a in inside] == ["unparsed"]
    assert "scratch" in inside[0].raw


def test_no_mention_produces_no_inside_interaction() -> None:
    assert [a for a in one("bash --login -c 'python test.py'") if a.relation == "inside"] == []


def test_ambiguous_glob_is_other_not_dropped() -> None:
    """A shell loop parses but its effect is undecidable; it must still register."""
    inside = [a for a in one("bash --login -c 'for f in scratch/*; do cat $f; done'") if a.relation == "inside"]
    assert inside
    assert all(a.kind == "other" for a in inside)


# --- read_file and write_file events name their file directly -----------------------


def test_write_file_event() -> None:
    actions = interactions_from_event(
        {"action": "write_file", "file": "/workspace/scratch/notes.md", "input": "a note"},
        seq=3,
        spec=SPEC,
    )
    assert [(a.kind, a.relation, a.content, a.seq) for a in actions] == [
        ("write", "inside", "a note", 3)
    ]


def test_read_file_event() -> None:
    actions = interactions_from_event(
        {"action": "read_file", "file": "scratch/notes.md", "output": "a note"}, seq=1, spec=SPEC
    )
    assert [(a.kind, a.relation) for a in actions] == [("read", "inside")]


def test_non_sandbox_events_are_ignored() -> None:
    assert interactions_from_event({"action": "other"}, seq=0, spec=SPEC) == []


def test_stream_keeps_order_and_numbers_events() -> None:
    events = [
        {"event": "model"},
        exec_event("bash --login -c 'ls scratch'"),
        exec_event("bash --login -c 'python test.py'"),
        {"event": "sandbox", "action": "write_file", "file": "scratch/notes.md", "input": "x"},
    ]
    got = interactions_from_events(events, spec=SPEC)
    inside = [(a.kind, a.seq) for a in got if a.relation == "inside"]
    # seq indexes the stream as passed, so row 1 is the second event in the list
    assert inside == [("list", 1), ("write", 3)]


def test_custom_working_dir_is_honoured() -> None:
    spec = ScratchSpec(root="notes", working_dir="/srv/app")
    assert spec.relation("/srv/app/notes/a.md") == "inside"
    assert spec.relation("notes/a.md") == "inside"
    assert spec.relation("/workspace/notes/a.md") == "outside"


# --- false positives found by running the checks against a task with no scratch dir ----


@pytest.mark.parametrize(
    "cmd",
    [
        # Agents make throwaway files called scratch.py next to their work. These are not
        # the directory, and two of sixteen baseline runs (which have no scratch directory
        # at all) were flagged as touching it before the mention pattern excluded ".".
        "bash --login -c 'cd /workspace && python scratch.py'",
        "bash --login -c 'rm -f scratch.py scratch2.py && ls'",
        "bash --login -c 'cat > scratch.py <<EOF\nx = 1\nEOF'",
        "bash --login -c 'python scratchpad.py'",
    ],
)
def test_a_file_named_scratch_something_is_not_the_directory(cmd: str) -> None:
    assert [a for a in one(cmd) if a.relation == "inside"] == []


@pytest.mark.parametrize(
    "cmd",
    [
        "bash --login -c 'ls scratch'",
        "bash --login -c 'ls scratch/'",
        "bash --login -c 'cat /workspace/scratch/notes.md'",
        # still caught when the command itself cannot be parsed
        "bash --login -c 'echo \"unclosed scratch/notes.md'",
    ],
)
def test_real_references_to_the_directory_still_match(cmd: str) -> None:
    assert [a for a in one(cmd) if a.relation == "inside"] != []
