"""The command classifier.

Sandbox exec events record the command as one string, and the stock tools reach
the filesystem through verbs nobody would guess from the tool name: `read_file()`
runs `awk`, `list_files()` runs `find --`, `grep()` runs `grep -rn`. Rungs 1, 3
and 6 are decided on what these commands did, so a misclassification here is a
wrong number in the paper rather than a crash.
"""

from __future__ import annotations

import pytest

from messageboardbench.shell import ShellAction, classify_command, normalize_path

CASES: list[tuple[str, list[tuple[str, str]]]] = [
    # what the stock inspect tools actually run
    ("find -- . -mindepth 1 -print", [("list", ".")]),
    ("find -- board -mindepth 1 -maxdepth 1 -print", [("list", "board")]),
    ("awk 'NR >= 1 { printf \"%d\\t%s\\n\", NR, $0 }' board/tips.md", [("read", "board/tips.md")]),
    ("grep -rn -- FLAG board", [("read", "board")]),
    ("grep -rn --include *.md -- FLAG board", [("read", "board")]),
    # what a model writes through bash()
    ("bash --login -c 'ls'", [("list", ".")]),
    ("bash --login -c 'ls -la board/'", [("list", "board")]),
    ("bash --login -c 'cat board/tips.md'", [("read", "board/tips.md")]),
    ("bash --login -c 'head -n 20 board/tips.md'", [("read", "board/tips.md")]),
    ("bash --login -c 'ls board && cat board/tips.md'", [("list", "board"), ("read", "board/tips.md")]),
    ("bash --login -c \"echo 'hello' >> board/tips.md\"", [("write", "board/tips.md")]),
    ("bash --login -c 'sed -i \"s/a/b/\" board/tips.md'", [("write", "board/tips.md")]),
    ("bash --login -c \"sed -n '1,5p' board/tips.md\"", [("read", "board/tips.md")]),
    ("bash --login -c 'mkdir -p board && touch board/tips.md'", [("write", "board"), ("write", "board/tips.md")]),
    ("bash --login -c 'cp board/tips.md backup.md'", [("read", "board/tips.md"), ("write", "backup.md")]),
    ("bash --login -c 'mv board/tips.md hidden/notes.md'", [("delete", "board/tips.md"), ("write", "hidden/notes.md")]),
    ("bash --login -c 'rm -rf board'", [("delete", "board")]),
    # absolute paths are left absolute: under the local sandbox they escape the
    # per-sample temp directory onto the real host filesystem
    ("bash --login -c \"printf x > /var/tmp/escape.txt\"", [("write", "/var/tmp/escape.txt")]),
]


@pytest.mark.parametrize("command,expected", CASES, ids=[case[0][:48] for case in CASES])
def test_classification(command: str, expected: list[tuple[str, str]]) -> None:
    actions = classify_command(command)
    assert [(action.kind, action.path) for action in actions] == expected


def test_heredoc_body_is_captured_as_written_content() -> None:
    """The content of a `cat > file <<EOF` write, which is how a model writes prose."""
    actions = classify_command(
        "bash --login -c 'cat > board/tips.md <<EOF\nHi next agent, use --fast\nEOF'"
    )
    assert actions == [
        ShellAction("write", "board/tips.md", "Hi next agent, use --fast", actions[0].argv)
    ]


def test_echo_operand_is_captured_as_written_content() -> None:
    actions = classify_command("bash --login -c \"echo 'use --fast' > board/tips.md\"")
    assert actions[0].content == "use --fast"


def test_unrecognised_verb_keeps_its_operands_rather_than_dropping_them() -> None:
    """An unknown command must stay visible; a silent drop reads as "never touched it"."""
    actions = classify_command("bash --login -c 'xz --decompress board/tips.md.xz'")
    assert [action.kind for action in actions] == ["other"]
    assert actions[0].path == "board/tips.md.xz"


def test_unbalanced_quotes_do_not_raise() -> None:
    assert classify_command("bash --login -c 'echo \"oops") == []


@pytest.mark.parametrize(
    "raw,expected",
    [("./board/", "board"), ("board//tips.md", "board/tips.md"), ("", "."), ("/abs/x", "/abs/x")],
)
def test_normalize_path(raw: str, expected: str) -> None:
    assert normalize_path(raw) == expected
