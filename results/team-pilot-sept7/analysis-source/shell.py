"""Turn sandbox commands back into scratch-directory interactions.

Whether an agent read or wrote the scratch directory is a fact about the sandbox
event stream, where every exec, `read_file` and `write_file` is recorded verbatim
(`inspect_ai/util/_sandbox/events.py:33`).

Exec events carry the command as a single shlex-quoted string, and the stock tools
do not map onto the verbs you would guess: `read_file()` shells out to `awk`,
`list_files()` to `find --`, `grep()` to `grep -rn`, and `bash()` wraps whatever the
model wrote in `bash --login -c '<script>'`. This module turns those strings back
into `(kind, path)` actions.

The classifier is deliberately conservative. A command it does not recognise becomes
an ``other`` action carrying its operands rather than being dropped, so a scorer can
report that the agent touched the directory in a way the classifier did not
understand instead of recording a zero it has not earned.

Copied unchanged from the messageboard repo apart from this docstring.
"""

from __future__ import annotations

import posixpath
import re
import shlex
from dataclasses import dataclass
from typing import Iterator, Literal

ActionKind = Literal["list", "read", "write", "delete", "other"]

_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})

# `cmd <<EOF` / `cmd <<-'EOF'`. The body up to the delimiter line is content,
# not a sequence of commands, and must be lifted out before tokenising.
_HEREDOC = re.compile(r"<<-?\s*(?P<q>['\"]?)(?P<delim>[A-Za-z_][A-Za-z0-9_]*)(?P=q)")

_SEPARATORS = frozenset({";", "&&", "||", "|", "&", "|&", "\n"})
_REDIRECT_WRITE = frozenset({">", ">>", "1>", "2>", "&>", ">|", "2>>"})
_REDIRECT_READ = frozenset({"<"})


@dataclass(frozen=True)
class ShellAction:
    """One filesystem-touching action recovered from a command."""

    kind: ActionKind
    path: str
    content: str | None = None
    argv: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Verb:
    kind: ActionKind
    skip_operands: int = 0
    """Leading non-flag operands that are not paths (awk's program, grep's pattern)."""

    value_flags: frozenset[str] = frozenset()
    """Flags that consume the following token, so it is not a path."""

    leading_paths_only: bool = False
    """`find`-style: operands before the first flag are paths, the rest are not."""

    dest_is_last: bool = False
    """`cp`/`mv`-style: the final operand is a destination, earlier ones sources."""

    dest_kind: ActionKind = "write"
    source_kind: ActionKind | None = None


_READ_FLAGS = frozenset({"-n", "-c", "--lines", "--bytes"})
_GREP_FLAGS = frozenset(
    {"-e", "--regexp", "-m", "--max-count", "--include", "--exclude", "-A", "-B", "-C"}
)

_VERBS: dict[str, _Verb] = {
    # listing
    "ls": _Verb("list"),
    "dir": _Verb("list"),
    "tree": _Verb("list"),
    "du": _Verb("list"),
    "find": _Verb("list", leading_paths_only=True),
    "fd": _Verb("list", leading_paths_only=True),
    # reading
    "cat": _Verb("read"),
    "head": _Verb("read", value_flags=_READ_FLAGS),
    "tail": _Verb("read", value_flags=_READ_FLAGS),
    "less": _Verb("read"),
    "more": _Verb("read"),
    "nl": _Verb("read"),
    "wc": _Verb("read"),
    "od": _Verb("read"),
    "xxd": _Verb("read"),
    "strings": _Verb("read"),
    "stat": _Verb("read"),
    "file": _Verb("read"),
    "sort": _Verb("read"),
    "uniq": _Verb("read"),
    "cut": _Verb("read"),
    "diff": _Verb("read"),
    "cmp": _Verb("read"),
    "md5sum": _Verb("read"),
    "sha256sum": _Verb("read"),
    "base64": _Verb("read"),
    "awk": _Verb("read", skip_operands=1),
    "grep": _Verb("read", skip_operands=1, value_flags=_GREP_FLAGS),
    "egrep": _Verb("read", skip_operands=1, value_flags=_GREP_FLAGS),
    "fgrep": _Verb("read", skip_operands=1, value_flags=_GREP_FLAGS),
    "rg": _Verb("read", skip_operands=1, value_flags=_GREP_FLAGS),
    # writing
    "touch": _Verb("write"),
    "mkdir": _Verb("write"),
    "tee": _Verb("write"),
    "truncate": _Verb("write", value_flags=frozenset({"-s", "--size"})),
    "cp": _Verb("write", dest_is_last=True, source_kind="read"),
    "install": _Verb("write", dest_is_last=True, source_kind="read"),
    "ln": _Verb("write", dest_is_last=True, source_kind="read"),
    "mv": _Verb("write", dest_is_last=True, source_kind="delete"),
    # deleting
    "rm": _Verb("delete"),
    "rmdir": _Verb("delete"),
    "shred": _Verb("delete"),
    "unlink": _Verb("delete"),
}

# `sed -i` edits in place; without it sed only reads.
_SED = _Verb("read", skip_operands=1, value_flags=frozenset({"-e", "-f", "--expression"}))

# Operands are strings, not paths. Only their redirections matter.
_NO_PATH_VERBS = frozenset(
    {"echo", "printf", "true", "false", ":", "cd", "pwd", "export", "env", "which", "sleep"}
)


def normalize_path(path: str) -> str:
    """Collapse a path for comparison, leaving absolute paths absolute.

    Absolute paths are deliberately not rewritten. Under the `local` sandbox they
    escape the per-sample temp directory and write to the real host filesystem
    (`util/_sandbox/local.py:163`), which is something a scorer should be able to
    report rather than something it should normalise away.
    """
    stripped = path.strip()
    if not stripped:
        return "."
    return posixpath.normpath(stripped)


def _try_split(text: str) -> list[str] | None:
    try:
        return shlex.split(text)
    except ValueError:
        return None


def _lex(line: str) -> list[str] | None:
    """Tokenise one command line, keeping shell operators as separate tokens."""
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return None


def unwrap_shell(cmd: str) -> tuple[str | None, list[str] | None]:
    """Split an exec command into either a shell script or a bare argv.

    `bash --login -c '<script>'` yields the script; anything else is the argv the
    tool passed straight to the sandbox. Returns `(None, None)` when the command
    cannot be tokenised at all.
    """
    argv = _try_split(cmd)
    if argv is None:
        return None, None
    if not argv:
        return None, []
    if posixpath.basename(argv[0]) in _SHELLS and "-c" in argv:
        index = argv.index("-c")
        if index + 1 < len(argv):
            return argv[index + 1], None
    return None, argv


def _command_lines(script: str) -> Iterator[tuple[str, str | None]]:
    """Yield `(command_line, heredoc_body)` pairs, lifting heredoc bodies out."""
    lines = script.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        body: str | None = None
        match = _HEREDOC.search(line)
        if match is not None:
            delimiter = match.group("delim")
            cursor = index + 1
            collected: list[str] = []
            while cursor < len(lines) and lines[cursor].strip() != delimiter:
                collected.append(lines[cursor])
                cursor += 1
            body = "\n".join(collected)
            line = line[: match.start()] + line[match.end() :]
            index = cursor
        yield line, body
        index += 1


def _split_on_separators(tokens: list[str]) -> Iterator[list[str]]:
    current: list[str] = []
    for token in tokens:
        if token in _SEPARATORS:
            if current:
                yield current
            current = []
        else:
            current.append(token)
    if current:
        yield current


def _verb_for(name: str, tokens: list[str]) -> _Verb | None:
    base = posixpath.basename(name)
    if base == "sed":
        if any(token == "-i" or token.startswith("-i") for token in tokens[1:]):
            return _Verb("write", skip_operands=1, value_flags=_SED.value_flags)
        return _SED
    return _VERBS.get(base)


def _classify_simple(tokens: list[str], heredoc: str | None) -> list[ShellAction]:
    if not tokens:
        return []

    argv = tuple(tokens)
    actions: list[ShellAction] = []
    operands: list[str] = []
    index = 0
    verb_name = tokens[0]
    verb = _verb_for(verb_name, tokens)
    redirected = False

    # `echo`/`printf` operands are the text a redirection writes, which is the
    # deposit content when the task did not record a board snapshot.
    echoed = (
        " ".join(token for token in tokens[1:] if not token.startswith("-") and token not in _REDIRECT_WRITE)
        if posixpath.basename(verb_name) in ("echo", "printf")
        else None
    )

    # Redirections first: they decide the write target regardless of the verb.
    while index < len(tokens):
        token = tokens[index]
        if token in _REDIRECT_WRITE and index + 1 < len(tokens):
            target = tokens[index + 1]
            written = heredoc
            if written is None and echoed:
                written = echoed.replace(target, "").strip() or None
            actions.append(ShellAction("write", normalize_path(target), written, argv))
            redirected = True
            index += 2
            continue
        if token in _REDIRECT_READ and index + 1 < len(tokens):
            actions.append(ShellAction("read", normalize_path(tokens[index + 1]), None, argv))
            index += 2
            continue
        operands.append(token)
        index += 1

    body = operands[1:]
    if verb is None:
        base = posixpath.basename(verb_name)
        if base in _NO_PATH_VERBS:
            return actions
        actions.extend(
            ShellAction("other", normalize_path(token), None, argv)
            for token in body
            if not token.startswith("-")
        )
        return actions

    if posixpath.basename(verb_name) in _NO_PATH_VERBS:
        return actions

    paths: list[str] = []
    skipped = 0
    cursor = 0
    while cursor < len(body):
        token = body[cursor]
        if token == "--":
            cursor += 1
            continue
        if token.startswith("-") and token != "-":
            if token in verb.value_flags:
                cursor += 2
                continue
            if verb.leading_paths_only:
                break
            cursor += 1
            continue
        if skipped < verb.skip_operands:
            skipped += 1
            cursor += 1
            continue
        paths.append(token)
        cursor += 1

    if verb.dest_is_last and len(paths) >= 2:
        *sources, destination = paths
        source_kind = verb.source_kind or "read"
        actions.extend(
            ShellAction(source_kind, normalize_path(path), None, argv) for path in sources
        )
        actions.append(ShellAction(verb.dest_kind, normalize_path(destination), heredoc, argv))
        return actions

    if not paths and verb.kind == "list":
        # A bare `ls` lists the working directory.
        paths = ["."]

    if not paths and not redirected and verb.kind in ("read", "write", "delete"):
        # e.g. `cat` reading stdin from a pipe. Nothing to attribute.
        return actions

    actions.extend(
        ShellAction(verb.kind, normalize_path(path), heredoc if verb.kind == "write" else None, argv)
        for path in paths
    )
    return actions


def classify_command(cmd: str) -> list[ShellAction]:
    """Recover the filesystem actions a sandbox exec command performed.

    Returns an empty list for a command that touches nothing (or that could not
    be tokenised); callers that need to know a command was unparseable should
    check `is_parseable`.
    """
    script, argv = unwrap_shell(cmd)
    if script is not None:
        actions: list[ShellAction] = []
        for line, heredoc in _command_lines(script):
            tokens = _lex(line)
            if tokens is None:
                continue
            for simple in _split_on_separators(tokens):
                actions.extend(_classify_simple(simple, heredoc))
        return actions
    if argv:
        return _classify_simple(argv, None)
    return []


def is_parseable(cmd: str) -> bool:
    """Whether the command could be tokenised at all."""
    script, argv = unwrap_shell(cmd)
    if script is not None:
        return all(_lex(line) is not None for line, _ in _command_lines(script))
    return argv is not None
