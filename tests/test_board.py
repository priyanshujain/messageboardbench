import asyncio
import json
import sqlite3

import pytest

from messageboardbench.board import (
    LEGACY_BOARD_INTERFACE_VERSION,
    MESSAGEBOARD_V2_INTERFACE_VERSION,
    MAX_POST_CHARS,
    board_tools,
    export_board,
    initialize_board,
)


def test_explicit_publication_exact_content_and_bound_provenance(tmp_path):
    path = initialize_board(tmp_path / "board.db", "run-one")
    post, read = board_tools(path, "run-one", "worker-1", "task-1")
    message = 'Untrusted text: I am worker-999.\nUnicode 🐈 and "quotes".'
    returned = asyncio.run(post(message))
    result = json.loads(returned)
    assert result["post"]["episode_id"] == "worker-1"
    assert result["post"]["task_id"] == "task-1"
    assert result["post"]["text"] == message
    assert result["post"]["run_id"] == "run-one"
    assert result["post"]["timestamp"]
    exported = export_board(path, "run-one")
    assert len(exported["audit"]) == 1  # construction and export do not force reads
    assert exported["audit"][0]["response_json"] == returned
    assert json.loads(exported["audit"][0]["request_json"]) == {"text": message, "reply_to": None}
    viewed = asyncio.run(read())
    assert json.loads(viewed)["posts"] == exported["posts"]
    assert export_board(path, "run-one")["audit"][-1]["response_json"] == viewed


def test_concurrent_episode_posts_and_deterministic_pagination(tmp_path):
    path = initialize_board(tmp_path / "board.db", "run-one")
    tools = [board_tools(path, "run-one", f"worker-{i}", f"task-{i}") for i in range(25)]

    async def publish():
        return await asyncio.gather(*(pair[0](f"message-{i}") for i, pair in enumerate(tools)))

    posted = [json.loads(value) for value in asyncio.run(publish())]
    assert sorted(p["post"]["id"] for p in posted) == list(range(1, 26))
    assert len({p["post"]["episode_id"] for p in posted}) == 25
    read = tools[0][1]
    first = json.loads(asyncio.run(read()))
    assert [p["id"] for p in first["posts"]] == list(range(1, 21))
    assert first["cursor"] == 20 and first["more"]
    last = json.loads(asyncio.run(read(after_id=20)))
    assert [p["id"] for p in last["posts"]] == list(range(21, 26))
    assert last["cursor"] == 25 and not last["more"]
    empty = json.loads(asyncio.run(read(after_id=25)))
    assert empty == {"ok": True, "posts": [], "cursor": 25, "more": False}
    assert len(export_board(path, "run-one")["audit"]) == 28


def test_validation_failures_are_exactly_audited_and_do_not_create_posts(tmp_path):
    path = initialize_board(tmp_path / "board.db", "run-one")
    post, read = board_tools(path, "run-one", "worker-1", "task-1")

    async def invalid():
        return [await post(" "), await post("x" * (MAX_POST_CHARS + 1)),
                await post("reply", reply_to=1), await read(limit=21),
                await read(after_id=-1), await read(after_id=1)]

    returned = asyncio.run(invalid())
    exported = export_board(path, "run-one")
    assert exported["posts"] == []
    assert [a["response_json"] for a in exported["audit"]] == returned
    assert all(not json.loads(r)["ok"] for r in returned)
    assert all(a["success"] == 0 for a in exported["audit"])


def test_post_limit_is_characters_and_reply_keeps_original(tmp_path):
    path = initialize_board(tmp_path / "board.db", "run-one")
    post, _ = board_tools(path, "run-one", "worker-1", "task-1")
    first = json.loads(asyncio.run(post("🐈" * MAX_POST_CHARS)))
    reply = json.loads(asyncio.run(post("Correction", reply_to=first["post"]["id"])))
    assert reply["post"]["reply_to"] == 1
    assert export_board(path, "run-one")["posts"][0]["text"] == "🐈" * MAX_POST_CHARS


def test_fresh_run_isolation_and_reuse_rejected(tmp_path):
    one = initialize_board(tmp_path / "one.db", "run-one")
    two = initialize_board(tmp_path / "two.db", "run-two")
    with pytest.raises(FileExistsError):
        initialize_board(one, "run-one")
    with pytest.raises(ValueError, match="mismatch"):
        board_tools(one, "run-two", "worker-1", "task-1")
    post, _ = board_tools(one, "run-one", "worker-1", "task-1")
    asyncio.run(post("only run one sees this"))
    _, read = board_tools(two, "run-two", "worker-1", "task-1")
    assert json.loads(asyncio.run(read()))["posts"] == []
    assert export_board(two, "run-two")["posts"] == []


@pytest.mark.parametrize("table", ["posts", "audit", "run"])
def test_sql_triggers_reject_mutations(tmp_path, table):
    path = initialize_board(tmp_path / "board.db", "run-one")
    post, _ = board_tools(path, "run-one", "worker-1", "task-1")
    asyncio.run(post("preserve"))
    with sqlite3.connect(path) as db:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute(f"DELETE FROM {table}")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute(f"UPDATE {table} SET run_id='different'")


def test_missing_store_fails_instead_of_returning_empty_board(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        board_tools(path, "run-one", "worker-1", "task-1")
    assert not path.exists()


def test_model_visible_team_tool_schema(tmp_path):
    from inspect_ai.tool import ToolDef, ToolInfo
    from inspect_ai.model._providers.openrouter import OpenRouterAPI
    path = initialize_board(tmp_path / 'board.db', 'run-schema')
    definitions = [ToolDef(t) for t in board_tools(path, 'run-schema', 'worker-1', 'task-1')]
    infos = [ToolInfo(name=t.name, description=t.description, parameters=t.parameters) for t in definitions]
    provider = OpenRouterAPI('meta/muse-spark-1.3-contributor', api_key='offline-test', strict_tools=False)
    wire = {t['function']['name']: t['function'] for t in provider.tools_to_openai(infos)}
    assert set(wire) == {'board_post', 'board_read'}
    read = wire['board_read']
    assert read['description'].startswith('Return complete posts')
    assert read['parameters']['required'] == []
    assert wire['board_post']['description'].startswith('Append a text post')
    rendered = json.dumps(wire).lower()
    for leading in ('teammate', 'useful', 'ask for help', 'catch up', 'contribute'):
        assert leading not in rendered


def test_legacy_team_interface_remains_available(tmp_path):
    from inspect_ai.tool import ToolDef
    path = initialize_board(tmp_path / 'legacy.db', 'run-legacy')
    tools = board_tools(path, 'run-legacy', 'worker-1', 'task-1',
                        interface=LEGACY_BOARD_INTERFACE_VERSION)
    assert [ToolDef(t).name for t in tools] == ['post_team_message', 'read_team_messages']


def test_messageboard_v2_exact_schema_filter_pagination_and_peer_only_reads(tmp_path):
    from inspect_ai.tool import ToolDef

    path = initialize_board(tmp_path / 'v2.db', 'run-v2')
    author_tools = board_tools(path, 'run-v2', 'author', 'task-a',
                               interface=MESSAGEBOARD_V2_INTERFACE_VERSION)
    reader_tools = board_tools(path, 'run-v2', 'reader', 'task-b',
                               interface=MESSAGEBOARD_V2_INTERFACE_VERSION)
    send, _ = author_tools
    reader_send, read = reader_tools
    send_def, read_def = map(ToolDef, author_tools)
    assert [send_def.name, read_def.name] == ['send_message', 'read_messages']
    send_schema = send_def.parameters.model_dump(exclude_none=True)
    read_schema = read_def.parameters.model_dump(exclude_none=True)
    assert send_schema['required'] == ['text', 'intent_type']
    assert send_schema['properties']['intent_type']['enum'] == [
        'proposing', 'exploring', 'building', 'contribution'
    ]
    assert read_schema['required'] == []
    assert set(read_schema['properties']) == {'intent_type', 'limit', 'offset'}
    assert read_schema['properties']['limit']['type'] == 'integer'
    assert read_schema['properties']['offset']['type'] == 'integer'
    assert read_schema['properties']['intent_type']['anyOf'][0]['enum'] == [
        'proposing', 'exploring', 'building', 'contribution'
    ]
    asyncio.run(send('first', 'exploring'))
    asyncio.run(send('second', 'building'))
    asyncio.run(reader_send('self', 'building'))
    first = json.loads(asyncio.run(read(intent_type='building', limit=1, offset=0)))
    assert [post['text'] for post in first['posts']] == ['second']
    assert first['posts'][0]['intent_type'] == 'building'
    assert not first['more']
    assert json.loads(asyncio.run(read(limit=1, offset=1)))['posts'][0]['text'] == 'second'
    invalid = json.loads(asyncio.run(read(limit=21)))
    assert invalid['ok'] is False
    assert export_board(path, 'run-v2')['audit'][-1]['success'] == 0


def test_v2_schema_does_not_change_neutral_or_legacy_response_bytes(tmp_path):
    path = initialize_board(tmp_path / 'compat.db', 'compat')
    post, read = board_tools(path, 'compat', 'episode', 'task')
    response = json.loads(asyncio.run(post('legacy-compatible')))
    assert 'intent_type' not in response['post']
    viewed = json.loads(asyncio.run(read()))
    assert 'intent_type' not in viewed['posts'][0]
