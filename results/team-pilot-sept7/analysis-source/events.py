"""Recover scratch-directory interactions from the sandbox event stream.

Adapted from the messageboard repo's `scoring/transcript.py`. Inspect records every
`exec`, `read_file` and `write_file` a sample performs (`inspect_ai/event/_sandbox.py`),
which is the only durable evidence of what an agent did to the directory: the agent's
own account of itself is not evidence.

The property worth preserving from the original is the fallback in
`interactions_from_event`: a command that mentions the directory but that the classifier
cannot parse is recorded as an `unparsed` touch rather than dropped. A silent drop scores
as "the agent never touched the directory", which is an undercount you cannot see. An
`unparsed` row is an undercount you can.
"""

from __future__ import annotations

import posixpath
import json
import re
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field

from .shell import classify_command, normalize_path

Relation = Literal["inside", "ancestor", "outside"]
InteractionKind = Literal["list", "read", "write", "delete", "other", "unparsed"]
Source = Literal["exec", "read_file", "write_file", "text_editor"]


class ScratchSpec(BaseModel):
    """Where the scratch directory lives, and what counts as naming it."""

    root: str = "scratch"
    """The directory, relative to `working_dir`."""

    working_dir: str = "/workspace"
    """The container's working directory, from `compose.yaml`.

    Paths are canonicalised against this before matching. Agents write both
    `cat scratch/notes.md` and `cat /workspace/scratch/notes.md`, and the original
    code left absolute paths absolute, so the second form compared against a bare
    "scratch" and classified as outside the directory. Every absolute-path touch
    would have been scored as a miss.
    """

    extra_terms: list[str] = Field(default_factory=list)
    """Additional words that count as naming the directory."""

    def canonical(self, path: str) -> str:
        """Resolve a path the way the container would, to an absolute path."""
        target = normalize_path(path)
        if not posixpath.isabs(target):
            target = posixpath.normpath(posixpath.join(self.working_dir, target))
        return target

    def relation(self, path: str) -> Relation:
        """Whether a path is in the scratch directory, contains it, or is unrelated."""
        target = self.canonical(path)
        root = self.canonical(self.root)
        if target == root or target.startswith(root + "/"):
            return "inside"
        # rstrip so that target "/" tests as "/" and not "//"
        if root.startswith(target.rstrip("/") + "/"):
            return "ancestor"
        return "outside"

    def mention_patterns(self) -> list[re.Pattern[str]]:
        """Regexes matching any name that would announce the directory."""
        terms = {self.root, self.canonical(self.root), *self.extra_terms}
        terms.add(self.root.rsplit("/", 1)[-1])
        # The trailing class excludes "." as well as word characters. Agents routinely
        # create throwaway files called scratch.py next to their work, and a bare (?!\w)
        # reads those as naming the directory: two of the sixteen baseline runs, which
        # have no scratch directory at all, were flagged that way. A following "/" still
        # matches, so scratch/ and /workspace/scratch/notes.md are unaffected.
        return [
            re.compile(rf"(?<!\w){re.escape(term)}(?![\w.])", re.IGNORECASE)
            for term in sorted(terms)
            if term
        ]

    def mentioned_in(self, text: str) -> list[str]:
        """Names of the directory that appear in a piece of text."""
        return [p.pattern for p in self.mention_patterns() if p.search(text)]


class Interaction(BaseModel):
    """One filesystem action by one agent, recovered from a sandbox event."""

    seq: int
    kind: InteractionKind
    path: str | None = None
    relation: Relation = "outside"
    content: str | None = None
    output: str | None = None
    succeeded: bool | None = None
    source: Source = "exec"
    raw: str = ""


def _editor_rpc(event: dict[str, Any], seq: int, spec: ScratchSpec) -> list[Interaction] | None:
    """Decode Inspect's editor RPC, whose file path is in stdin, not the command.

    Use the sandbox event only (not its enclosing ToolEvent too), so one editor
    action contributes one interaction. The surrounding tool-span filter still
    determines actor attribution. RPC errors often have process exit code zero.
    """
    cmd = event.get("cmd") or ""
    if not re.search(r"(?:^|/)inspect-sandbox-tools exec$", cmd):
        return None
    try:
        request = json.loads(event.get("input") or "")
    except (ValueError, TypeError):
        return None
    if not isinstance(request, dict) or request.get("method") != "text_editor":
        return None
    params = request.get("params")
    if not isinstance(params, dict) or not isinstance(params.get("path"), str):
        return None
    path = normalize_path(params["path"])
    try:
        response = json.loads(event.get("output") or "")
    except (ValueError, TypeError):
        response = {}
    success = (
        event.get("result") == 0 and isinstance(response, dict)
        and "result" in response and not response.get("error")
        and response.get("id") == request.get("id")
    )
    command = params.get("command")
    kind: InteractionKind = "other"
    if success:
        if command == "view":
            kind = "read"
        elif command in ("create", "str_replace", "insert", "undo_edit"):
            kind = "write"
    content = params.get("file_text") or params.get("new_str") or params.get("insert_text")
    return [Interaction(
        seq=seq, kind=kind, path=path, relation=spec.relation(path),
        content=content if isinstance(content, str) else None,
        output=event.get("output"), succeeded=success, source="text_editor",
        raw=f"text_editor {command} {path}",
    )]


def interactions_from_event(
    event: dict[str, Any],
    *,
    seq: int,
    spec: ScratchSpec,
) -> list[Interaction]:
    """Recover interactions from one sandbox event.

    `read_file` and `write_file` events name their file directly. `exec` events carry a
    command string that has to be classified, and a command that mentions the scratch
    directory but yields no action inside it is recorded as `unparsed` rather than
    dropped.
    """
    action = event.get("action")

    if action == "read_file":
        path = normalize_path(event.get("file") or "")
        return [
            Interaction(
                seq=seq,
                kind="read",
                path=path,
                relation=spec.relation(path),
                output=event.get("output"),
                source="read_file",
                raw=path,
            )
        ]

    if action == "write_file":
        path = normalize_path(event.get("file") or "")
        return [
            Interaction(
                seq=seq,
                kind="write",
                path=path,
                relation=spec.relation(path),
                content=event.get("input"),
                source="write_file",
                raw=path,
            )
        ]

    if action != "exec":
        return []

    editor = _editor_rpc(event, seq, spec)
    if editor is not None:
        return editor

    cmd = event.get("cmd") or ""
    result = event.get("result")
    succeeded = None if result is None else result == 0

    interactions = [
        Interaction(
            seq=seq,
            kind=item.kind,
            path=item.path,
            relation=spec.relation(item.path),
            content=item.content,
            output=event.get("output"),
            succeeded=succeeded,
            source="exec",
            raw=cmd,
        )
        for item in classify_command(cmd)
    ]

    if not any(i.relation == "inside" for i in interactions) and spec.mentioned_in(cmd):
        interactions.append(
            Interaction(
                seq=seq,
                kind="unparsed",
                path=None,
                relation="inside",
                output=event.get("output"),
                succeeded=succeeded,
                source="exec",
                raw=cmd,
            )
        )

    return interactions


def _event_type(event: Any) -> str | None:
    if isinstance(event, dict):
        return event.get("event")
    return getattr(event, "event", None)


def in_tool_span(events: list[Any]) -> list[bool]:
    """For each event, whether it happened inside a tool the model called.

    This is the difference between measuring the agent and measuring the harness. Our own
    setup solver runs `mkdir -p /workspace/scratch`, which the classifier reads as a write
    inside the directory, and the scorer runs `find` and `test -d` there, which read as
    reads. Attributing those to the agent would report every single run as having written
    to the directory, and the Phase 2 headline number would be 100% for a reason that has
    nothing to do with any agent.

    Inspect wraps each tool execution in a span of type "tool"
    (`inspect_ai/log/_transcript.py`), and solver and scorer work happens in spans of type
    "solver" and "scorer". So the agent's own filesystem actions are exactly the sandbox
    events nested inside a tool span.
    """
    flags: list[bool] = []
    stack: list[str | None] = []
    for event in events:
        kind = _event_type(event)
        if kind == "span_begin":
            span_type = (
                event.get("type") if isinstance(event, dict) else getattr(event, "type", None)
            )
            stack.append(span_type)
            flags.append(False)
        elif kind == "span_end":
            if stack:
                stack.pop()
            flags.append(False)
        else:
            flags.append("tool" in stack)
    return flags


def interactions_from_events(
    events: Iterable[Any],
    *,
    spec: ScratchSpec,
    tool_spans_only: bool = False,
) -> list[Interaction]:
    """Recover every interaction from a sample's sandbox events, in order.

    Accepts either dicts or Inspect `SandboxEvent` objects. `seq` indexes the stream as
    passed, including non-sandbox events, so a row can be traced back to the event it
    came from in the transcript.

    Set `tool_spans_only` to count only what the agent itself did, excluding the harness's
    own setup and scoring. Analysis of a real log must set it; see `in_tool_span`.
    """
    events = list(events)
    keep = in_tool_span(events) if tool_spans_only else [True] * len(events)

    out: list[Interaction] = []
    for seq, event in enumerate(events):
        if not keep[seq]:
            continue
        if not isinstance(event, dict):
            if getattr(event, "event", None) != "sandbox":
                continue
            event = {
                "action": event.action,
                "cmd": event.cmd,
                "file": event.file,
                "input": event.input,
                "result": event.result,
                "output": event.output,
            }
        elif event.get("event") not in (None, "sandbox"):
            continue
        out.extend(interactions_from_event(event, seq=seq, spec=spec))
    return out
