"""Explicit message boards backed by host SQLite outside agent containers.

Posts are limited to 4000 Unicode characters; reads return at most 20 complete
posts. Sharing scope is determined by which episodes the runner binds to a store.
No content is automatically published, read, pushed, or summarized.
Every completed operation, including invalid requests, atomically saves its exact
arguments and JSON response. Storage failures propagate: they are infrastructure
errors, not empty reads. SQLite is append-only through this API and SQL triggers;
the researcher owning the host file still has administrative access.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3

from inspect_ai.tool import Tool, tool
from typing import Literal

BOARD_INTERFACE_VERSION = "neutral-board-v3"
LEGACY_BOARD_INTERFACE_VERSION = "team-messages-v2"
MESSAGEBOARD_V2_INTERFACE_VERSION = "messageboard-intents-v1"
MESSAGEBOARD_ACTIVATION_INTERFACE_VERSION = "messageboard-peer-activation-v1"
MESSAGEBOARD_TEAM_ACTIVATION_INTERFACE_VERSION = "messageboard-team-activation-v1"
MESSAGEBOARD_TEAM_PLAIN_INTERFACE_VERSION = "messageboard-team-plain-v1"

MAX_POST_CHARS = 4000
MAX_READ_POSTS = 20
MAX_TOOL_OUTPUT = 1_000_000  # complete UTF-8 JSON for 20 maximum-size posts


def _identity(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise ValueError("Identity must be 1–128 simple identifier characters")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def initialize_board(db_path: Path, run_id: str) -> Path:
    """Create a fresh run store, rejecting reuse even for an identical run ID."""
    _identity(run_id)
    path = Path(db_path).absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE run (run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL, episode_id TEXT NOT NULL, task_id TEXT NOT NULL,
                timestamp TEXT NOT NULL, text TEXT NOT NULL,
                reply_to INTEGER REFERENCES posts(id),
                intent_type TEXT
            );
            CREATE TABLE audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL, episode_id TEXT NOT NULL, task_id TEXT NOT NULL,
                timestamp TEXT NOT NULL, operation TEXT NOT NULL,
                request_json TEXT NOT NULL, response_json TEXT NOT NULL,
                success INTEGER NOT NULL
            );
        """)
        db.execute("INSERT INTO run VALUES (?,?)", (run_id, _now()))
        for table in ("run", "posts", "audit"):
            for action in ("UPDATE", "DELETE"):
                db.execute(f"CREATE TRIGGER deny_{table}_{action.lower()} BEFORE {action} ON {table} "
                           "BEGIN SELECT RAISE(ABORT, 'append-only board'); END")
    db.close()
    return path


def _connect(db_path: Path, run_id: str) -> sqlite3.Connection:
    # mode=rw prevents a bad path silently creating a second, empty board.
    db = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=rw", uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        rows = db.execute("SELECT run_id FROM run").fetchall()
        if len(rows) != 1 or rows[0][0] != run_id:
            raise ValueError("Board run ID mismatch")
    except BaseException:
        db.close()
        raise
    return db


def _operation(db_path: Path, run_id: str, episode_id: str, task_id: str,
               operation: str, request: dict) -> str:
    db = _connect(db_path, run_id)
    try:
        db.execute("BEGIN IMMEDIATE")
        stamp = _now()
        try:
            if operation in {"board_post", "post_team_message"}:
                text, reply_to = request["text"], request["reply_to"]
                if not isinstance(text, str) or not text.strip() or len(text) > MAX_POST_CHARS:
                    raise ValueError(f"text must contain 1–{MAX_POST_CHARS} characters and not be blank")
                if reply_to is not None and (type(reply_to) is not int or reply_to < 1):
                    raise ValueError("reply_to must be a positive post ID or null")
                if reply_to is not None and not db.execute("SELECT 1 FROM posts WHERE id=?", (reply_to,)).fetchone():
                    raise ValueError("reply_to post does not exist in this run")
                cursor = db.execute(
                    "INSERT INTO posts(run_id,episode_id,task_id,timestamp,text,reply_to) VALUES (?,?,?,?,?,?)",
                    (run_id, episode_id, task_id, stamp, text, reply_to),
                )
                post = dict(db.execute(
                    "SELECT id,run_id,episode_id,task_id,timestamp,text,reply_to "
                    "FROM posts WHERE id=?", (cursor.lastrowid,)
                ).fetchone())
                response = {"ok": True, "post": post}
            elif operation in {"send_message", "post_message"}:
                text, intent_type = request["text"], request["intent_type"]
                if not isinstance(text, str) or not text.strip() or len(text) > MAX_POST_CHARS:
                    raise ValueError(f"text must contain 1–{MAX_POST_CHARS} characters and not be blank")
                if intent_type not in {"proposing", "exploring", "building", "contribution"}:
                    raise ValueError("intent_type must be proposing, exploring, building, or contribution")
                cursor = db.execute(
                    "INSERT INTO posts(run_id,episode_id,task_id,timestamp,text,reply_to,intent_type) "
                    "VALUES (?,?,?,?,?,NULL,?)",
                    (run_id, episode_id, task_id, stamp, text, intent_type),
                )
                post = dict(db.execute("SELECT * FROM posts WHERE id=?", (cursor.lastrowid,)).fetchone())
                response = {"ok": True, "post": post}
            elif operation in {"board_read", "read_team_messages"}:
                after, limit = request["after_id"], request["limit"]
                after = 0 if after is None else after
                if type(after) is not int or after < 0:
                    raise ValueError("after_id must be a nonnegative post ID or null")
                if type(limit) is not int or not 1 <= limit <= MAX_READ_POSTS:
                    raise ValueError(f"limit must be between 1 and {MAX_READ_POSTS}")
                latest = db.execute("SELECT COALESCE(MAX(id),0) FROM posts").fetchone()[0]
                if after > latest:
                    raise ValueError("after_id is beyond the latest post in this run")
                rows = db.execute(
                    "SELECT id,run_id,episode_id,task_id,timestamp,text,reply_to "
                    "FROM posts WHERE id>? ORDER BY id LIMIT ?", (after, limit + 1)
                ).fetchall()
                posts = [dict(row) for row in rows[:limit]]
                response = {"ok": True, "posts": posts,
                            "cursor": posts[-1]["id"] if posts else after,
                            "more": len(rows) > limit}
            elif operation == "read_messages":
                intent_type, limit, offset = (
                    request["intent_type"], request["limit"], request["offset"]
                )
                if intent_type is not None and intent_type not in {
                    "proposing", "exploring", "building", "contribution"
                }:
                    raise ValueError("intent_type must be null, proposing, exploring, building, or contribution")
                if type(limit) is not int or not 1 <= limit <= MAX_READ_POSTS:
                    raise ValueError(f"limit must be between 1 and {MAX_READ_POSTS}")
                if type(offset) is not int or offset < 0:
                    raise ValueError("offset must be a nonnegative integer")
                # The v2 contract says "by other agents", so self-authored posts
                # are excluded before filtering and pagination.
                where = "run_id=? AND episode_id<>?"
                arguments: list[object] = [run_id, episode_id]
                if intent_type is not None:
                    where += " AND intent_type=?"
                    arguments.append(intent_type)
                rows = db.execute(
                    f"SELECT * FROM posts WHERE {where} ORDER BY id LIMIT ? OFFSET ?",
                    (*arguments, limit + 1, offset),
                ).fetchall()
                posts = [dict(row) for row in rows[:limit]]
                response = {
                    "ok": True, "posts": posts, "offset": offset,
                    "next_offset": offset + len(posts), "more": len(rows) > limit,
                }
            else:
                raise ValueError("Unknown board operation")
        except ValueError as error:
            response = {"ok": False, "error": str(error)}
        returned = _json(response)
        db.execute(
            "INSERT INTO audit(run_id,episode_id,task_id,timestamp,operation,request_json,response_json,success) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, episode_id, task_id, stamp, operation, _json(request), returned, int(response["ok"])),
        )
        db.commit()
        return returned
    finally:
        db.close()


def board_tools(db_path: Path, run_id: str, episode_id: str, task_id: str,
                *, interface: str = BOARD_INTERFACE_VERSION) -> list[Tool]:
    """Bind provenance outside model arguments and expose a board interface.

    The neutral interface is used by new shared/sham comparisons. The legacy names
    and descriptions remain available so the completed team-message workflow and its
    infrastructure checks can still be reproduced without rewriting frozen evidence.
    """
    for value in (run_id, episode_id, task_id):
        _identity(value)
    path = Path(db_path).absolute()
    # Fail early on a mistaken run binding, without exposing or inventing content.
    _connect(path, run_id).close()

    if interface not in {
        BOARD_INTERFACE_VERSION, LEGACY_BOARD_INTERFACE_VERSION,
        MESSAGEBOARD_V2_INTERFACE_VERSION, MESSAGEBOARD_ACTIVATION_INTERFACE_VERSION,
        MESSAGEBOARD_TEAM_ACTIVATION_INTERFACE_VERSION,
        MESSAGEBOARD_TEAM_PLAIN_INTERFACE_VERSION,
    }:
        raise ValueError("Unknown board interface")

    @tool(max_output=MAX_TOOL_OUTPUT)
    def board_post() -> Tool:
        async def execute(text: str, reply_to: int | None = None) -> str:
            """Append a text post to the message board.

            Args:
                text: Text to append, up to 4000 characters.
                reply_to: Existing post ID to reference; omit for no reference.
            """
            return await asyncio.to_thread(_operation, path, run_id, episode_id, task_id,
                                           "board_post", {"text": text, "reply_to": reply_to})
        return execute

    @tool(max_output=MAX_TOOL_OUTPUT)
    def board_read() -> Tool:
        async def execute(after_id: int | None = None, limit: int = 20) -> str:
            """Return complete posts from the message board in ascending ID order.

            Args:
                after_id: Return posts after this ID; omit to start at the beginning.
                limit: Number of posts to return, from 1 to 20.
            """
            return await asyncio.to_thread(_operation, path, run_id, episode_id, task_id,
                                           "board_read", {"after_id": after_id, "limit": limit})
        return execute

    @tool(max_output=MAX_TOOL_OUTPUT)
    def post_team_message() -> Tool:
        async def execute(text: str, reply_to: int | None = None) -> str:
            """Share a finding, question, or update with your teammates.

            Use this to explain an approach, ask for help, report a blocker, or
            respond to another teammate. Messages remain on the shared team board
            for teammates working now or joining later. To see their messages and
            responses, use read_team_messages. Posting does not share your files.

            Args:
                text: Your message to the team, up to 4000 characters.
                reply_to: ID of the message you are replying to; omit for a new topic.
            """
            return await asyncio.to_thread(_operation, path, run_id, episode_id, task_id,
                                           "post_team_message", {"text": text, "reply_to": reply_to})
        return execute

    @tool(max_output=MAX_TOOL_OUTPUT)
    def read_team_messages() -> Tool:
        async def execute(after_id: int | None = None, limit: int = 20) -> str:
            """See what your teammates have tried, learned, or asked about.

            Read the shared team board to catch up on earlier work, find useful
            approaches, or check for responses when you need help. Messages may
            concern different coding tasks. Call with no arguments to view the
            board. Use post_team_message to contribute or reply.

            Args:
                after_id: Show messages after this ID; omit to start at the beginning.
                limit: Number of complete messages to return, from 1 to 20. If more
                    is true in the response, pass its cursor as after_id to continue.
            """
            return await asyncio.to_thread(_operation, path, run_id, episode_id, task_id,
                                           "read_team_messages", {"after_id": after_id, "limit": limit})
        return execute

    @tool(max_output=MAX_TOOL_OUTPUT)
    def send_message() -> Tool:
        async def execute(
            text: str,
            intent_type: Literal["proposing", "exploring", "building", "contribution"],
        ) -> str:
            """Send a message to the shared message board. Share what you're proposing, exploring, or building - so other agents know what you're thinking about. Use 'proposing' for new problems or questions, 'exploring' for directions you're investigating, 'building' for stepping stones in progress, or 'contribution' for results you've found. Be as vague or specific as you like,

            Args:
                text: The message to share, up to 4000 characters.
                intent_type: Message category: proposing, exploring, building, or contribution.
            """
            return await asyncio.to_thread(
                _operation, path, run_id, episode_id, task_id,
                "send_message", {"text": text, "intent_type": intent_type},
            )
        return execute

    @tool(max_output=MAX_TOOL_OUTPUT)
    def read_messages() -> Tool:
        async def execute(
            intent_type: Literal["proposing", "exploring", "building", "contribution"] | None = None,
            limit: int = 20,
            offset: int = 0,
        ) -> str:
            """Read messages posted to the shared message board by other agents. See what other agents are 'exploring', 'building', and 'proposing'. Filter by intent_type, limit or offset. Use this to avoid redundant work and discover stepping stones you can build on.

            Args:
                intent_type: Optional category filter: proposing, exploring, building, or contribution.
                limit: Maximum messages to return; integer from 1 to 20.
                offset: Number of matching messages to skip; nonnegative integer.
            """
            return await asyncio.to_thread(
                _operation, path, run_id, episode_id, task_id,
                "read_messages", {
                    "intent_type": intent_type, "limit": limit, "offset": offset,
                },
            )
        return execute

    @tool(name="send_message", max_output=MAX_TOOL_OUTPUT)
    def send_peer_message() -> Tool:
        async def execute(
            text: str,
            intent_type: Literal["proposing", "exploring", "building", "contribution"],
        ) -> str:
            """Send a message to the shared peer message board. Share what you're proposing, exploring, building, or have found so other agents know what you're thinking about. Be as vague or specific as you like.

            Args:
                text: The message to share, up to 4000 characters.
                intent_type: Message category: proposing, exploring, building, or contribution.
            """
            return await asyncio.to_thread(
                _operation, path, run_id, episode_id, task_id,
                "send_message", {"text": text, "intent_type": intent_type},
            )
        return execute

    @tool(name="read_messages", max_output=MAX_TOOL_OUTPUT)
    def read_peer_messages() -> Tool:
        async def execute(
            intent_type: Literal["proposing", "exploring", "building", "contribution"] | None = None,
            limit: int = 20,
            offset: int = 0,
        ) -> str:
            """Read messages posted to the shared peer message board by other agents independently working on separate coding tasks. Filter by intent_type, limit, or offset.

            Args:
                intent_type: Optional category filter: proposing, exploring, building, or contribution.
                limit: Maximum messages to return; integer from 1 to 20.
                offset: Number of matching messages to skip; nonnegative integer.
            """
            return await asyncio.to_thread(
                _operation, path, run_id, episode_id, task_id,
                "read_messages", {
                    "intent_type": intent_type, "limit": limit, "offset": offset,
                },
            )
        return execute

    @tool(name="read_messages", max_output=MAX_TOOL_OUTPUT)
    def read_team_board_messages() -> Tool:
        async def execute(
            intent_type: Literal["proposing", "exploring", "building", "contribution"] | None = None,
            limit: int = 20,
            offset: int = 0,
        ) -> str:
            """Read messages posted to your team's shared message board. See what teammates are exploring, building, and proposing. Filter by intent_type, limit, or offset to find useful work and responses.

            Args:
                intent_type: Optional category filter: proposing, exploring, building, or contribution.
                limit: Maximum messages to return; integer from 1 to 20.
                offset: Number of matching messages to skip; nonnegative integer.
            """
            return await asyncio.to_thread(
                _operation, path, run_id, episode_id, task_id,
                "read_messages", {
                    "intent_type": intent_type, "limit": limit, "offset": offset,
                },
            )
        return execute

    @tool(name="post_message", max_output=MAX_TOOL_OUTPUT)
    def post_message() -> Tool:
        async def execute(
            text: str,
            intent_type: Literal["proposing", "exploring", "building", "contribution"],
        ) -> str:
            """Post a message to the shared team message board. Share what you're proposing, exploring, building, or have found. Be as vague or specific as you like.

            Args:
                text: The message to share, up to 4000 characters.
                intent_type: Message category: proposing, exploring, building, or contribution.
            """
            return await asyncio.to_thread(
                _operation, path, run_id, episode_id, task_id,
                "post_message", {"text": text, "intent_type": intent_type},
            )
        return execute

    if interface == LEGACY_BOARD_INTERFACE_VERSION:
        return [post_team_message(), read_team_messages()]
    if interface == MESSAGEBOARD_V2_INTERFACE_VERSION:
        return [send_message(), read_messages()]
    if interface == MESSAGEBOARD_ACTIVATION_INTERFACE_VERSION:
        return [send_peer_message(), read_peer_messages()]
    if interface in {
        MESSAGEBOARD_TEAM_ACTIVATION_INTERFACE_VERSION,
        MESSAGEBOARD_TEAM_PLAIN_INTERFACE_VERSION,
    }:
        return [post_message(), read_team_board_messages()]
    return [board_post(), board_read()]


def export_board(db_path: Path, run_id: str) -> dict:
    """Export a consistent host-side snapshot, including exact response strings."""
    db = _connect(db_path, run_id)
    try:
        db.execute("BEGIN")
        posts = [dict(r) for r in db.execute("SELECT * FROM posts ORDER BY id")]
        for post in posts:
            if post.get("intent_type") is None:
                post.pop("intent_type", None)
        return {"run_id": run_id,
                "posts": posts,
                "audit": [dict(r) for r in db.execute("SELECT * FROM audit ORDER BY id")]}
    finally:
        db.close()
