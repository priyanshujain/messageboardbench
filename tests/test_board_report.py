import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS

SPEC = importlib.util.spec_from_file_location('board_report', Path(__file__).parents[1] / 'scripts/board_report.py')
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


def fixture(posts, *, delivered=True, event_arguments=None, ok=True):
    response = {'ok': ok, 'posts': posts, 'cursor': 0, 'more': False}
    raw = json.dumps(response)
    audit = [{'id': 3, 'run_id': 'run', 'episode_id': 'reader', 'task_id': 'task-reader',
              'operation': 'board_read', 'request_json': json.dumps({'after_id': None, 'limit': 20}),
              'response_json': raw, 'success': int(ok)}]
    tool = NS(event='tool', function='board_read', id='call-1', result=raw,
              arguments={} if event_arguments is None else event_arguments)
    messages = [NS(role='tool', content=raw, tool_call_id='call-1', id='message-1')] if delivered else []
    sample = NS(events=[NS(event='model'), tool, NS(event='model')], messages=messages)
    return audit, sample


def post(author, id=1):
    return {'id': id, 'episode_id': author, 'task_id': 'task-author', 'text': 'A concrete finding'}


def test_empty_or_self_reads_are_not_peer_exposures():
    for posts in ([], [post('reader')]):
        audit, sample = fixture(posts)
        operations, edges = report.link_board_operations(audit, sample)
        assert operations[0]['delivery_confirmed']
        assert not edges


def test_actual_peer_response_has_exact_original_indices():
    audit, sample = fixture([post('reader'), post('other', 2)])
    operations, edges = report.link_board_operations(audit, sample)
    assert len(edges) == 1
    assert edges[0]['author_episode_id'] == 'other'
    assert edges[0]['post_id'] == 2
    assert edges[0]['event_index'] == 1
    assert edges[0]['message_index'] == 0
    assert edges[0]['audit_id'] == 3
    assert edges[0]['next_model_event_index'] == 2
    assert operations[0]['tool_call_id'] == 'call-1'


def test_audit_without_delivery_is_not_exposure():
    audit, sample = fixture([post('other')], delivered=False)
    operations, edges = report.link_board_operations(audit, sample)
    assert operations[0]['event_index'] == 1
    assert not operations[0]['delivery_confirmed']
    assert not edges


def test_request_mismatch_cannot_link_identical_response():
    audit, sample = fixture([post('other')], event_arguments={'limit': 1})
    operations, edges = report.link_board_operations(audit, sample)
    assert operations[0]['event_index'] is None
    assert not edges


def test_failed_read_is_not_exposure_even_if_malformed_posts_exist():
    audit, sample = fixture([post('other')], ok=False)
    assert not report.link_board_operations(audit, sample)[1]


def test_repeated_identical_reads_link_one_to_one():
    audit, sample = fixture([post('other')])
    audit.append({**audit[0], 'id': 4})
    sample.events.append(NS(event='tool', function='board_read', id='call-2',
                            result=audit[0]['response_json'], arguments={}))
    sample.messages.append(NS(role='tool', content=audit[0]['response_json'], tool_call_id='call-2', id='message-2'))
    operations, edges = report.link_board_operations(audit, sample)
    assert [o['event_index'] for o in operations] == [1, 3]
    assert [e['message_index'] for e in edges] == [0, 1]


def test_encrypted_reasoning_and_internal_payload_never_exported():
    text = report.plain_content([
        {'type': 'reasoning', 'reasoning': 'SECRET', 'redacted': True, 'internal': {'encrypted': 'SECRET2'}},
        {'type': 'reasoning', 'reasoning': 'Visible thought', 'signature': 'SECRET3', 'internal': 'SECRET4'},
        {'type': 'text', 'text': 'Visible answer'},
    ])
    assert 'SECRET' not in text
    assert 'Visible thought' in text and 'Visible answer' in text


def test_report_roundtrip_exports_metrics_artifacts_and_blank_annotations(tmp_path, monkeypatch):
    audit, sample = fixture([post('other')])
    class Model(NS):
        def model_dump(self): return vars(self)
    score = NS(value='I', explanation='Contradiction', metadata={
        'submitted_artifacts': {'func.py': 'def f(): return 1', 'test.py': 'assert f() == 2'},
        'scratch_files': {'note.txt': 'Private work'}})
    sample.metadata = {'episode_id': 'reader', 'run_id': 'run'}
    sample.scores = {'scorer': score}
    sample.model_usage = {'test': NS(input_tokens=20, input_tokens_cache_read=30,
        input_tokens_cache_write=None, output_tokens=10, reasoning_tokens=7, total_tokens=60)}
    sample.id = 'task-reader'; sample.uuid = 'sample-uuid'; sample.limit = None
    sample.error = None; sample.working_time = 2.0
    sample.events.append(NS(event='score', score=score, intermediate=True))
    log = NS(status='success', samples=[sample], eval=NS(model='mockllm/model',
        config=Model(message_limit=60), metadata={'condition': 'board', 'cohort': 1, 'split': 'conflicting'}))
    monkeypatch.setattr(report, 'read_eval_log', lambda *a, **kw: log)
    run = tmp_path/'run'; run.mkdir(); (run/'one.eval').write_bytes(b'fake fixture')
    (run/'board-final.json').write_text(json.dumps({'run_id': 'run', 'audit': audit, 'posts': [post('other')]}))
    out = tmp_path/'report'; result = report.generate_report(run, out)
    assert result['episodes'] == 1 and result['exposure_edges'] == 1
    row = json.loads((out/'episodes.json').read_text())[0]
    assert row['total_tokens'] == 60 and row['model_calls'] == 2
    assert row['split'] == 'conflicting' and row['condition'] == 'board'
    assert row['team'] == 1 and row['slot'] is None
    assert (out/'episode-001/final-func.py').read_text() == 'def f(): return 1'
    assert json.loads((out/'episode-001/scorer-artifacts.json').read_text())[0]['event_index'] == 3
    import csv
    annotations = list(csv.DictReader((out/'annotations.csv').open()))
    assert {a['behavior'] for a in annotations} == {'gaming','publication','exposure','adoption','rejection','correction'}
    assert all(not a['label'] for a in annotations)
    import pytest
    with pytest.raises(FileExistsError): report.generate_report(run, out)
    snapshot = run/'board-after-phase-1.json'
    (run/'board-final.json').rename(snapshot)
    log.status = 'started'
    partial = report.generate_report(run, tmp_path/'partial', snapshot)
    assert partial['episodes'] == 0
    assert partial['board_snapshot_path'] == str(snapshot.resolve())
    assert partial['explicit_board_snapshot']
    assert partial['report_scope'].startswith('partial')
    assert partial['skipped_logs'][0]['status'] == 'started'


def test_revised_read_name_preserves_exact_exposure_linkage():
    audit, sample = fixture([post('other')])
    audit[0]['operation'] = 'read_team_messages'
    sample.events[1].function = 'read_team_messages'
    linked, edges = report.link_board_operations(audit, sample)
    assert linked[0]['delivery_confirmed']
    assert len(edges) == 1 and edges[0]['author_episode_id'] == 'other'


def test_messageboard_v2_read_and_private_feedback_link_exactly():
    audit, sample = fixture([post('other')])
    audit[0].update(
        operation='read_messages',
        request_json=json.dumps({'intent_type': None, 'limit': 20, 'offset': 0}),
    )
    response = {'ok': True, 'posts': [post('other')], 'offset': 0,
                'next_offset': 1, 'more': False}
    raw = json.dumps(response)
    audit[0]['response_json'] = raw
    sample.events[1].function = 'read_messages'
    sample.events[1].result = raw
    sample.messages[0].content = raw
    linked, edges = report.link_board_operations(audit, sample)
    assert linked[0]['delivery_confirmed'] and len(edges) == 1

    feedback_response = json.dumps({'ok': True, 'receipt_id': 'opaque'})
    feedback_audit = [{
        'id': 4, 'run_id': 'feedback-run', 'episode_id': 'reader',
        'task_id': 'task-reader', 'condition': 'board',
        'request_json': json.dumps({'text': 'broken evaluator'}),
        'response_json': feedback_response, 'success': 1,
    }]
    feedback_event = NS(event='tool', function='submit_feedback', id='feedback-call',
                        result=feedback_response, arguments={'text': 'broken evaluator'})
    sample.events.append(feedback_event)
    sample.messages.append(NS(role='tool', content=feedback_response,
                              tool_call_id='feedback-call', id='feedback-message'))
    feedback = report.link_feedback_operations(feedback_audit, sample)
    assert feedback[0]['delivery_confirmed']
    assert feedback[0]['response']['receipt_id'] == 'opaque'


def test_independent_teams_repeated_tasks_and_local_audit_ids_stay_separate(tmp_path, monkeypatch):
    """Independent databases reuse IDs; the export must join by run and episode."""
    class Model(NS):
        def model_dump(self): return vars(self)

    run = tmp_path / 'run'
    run.mkdir()
    logs, all_audit, posts = {}, [], []
    for team in (1, 2):
        run_id = f'run-{team}'
        donor_id = f'team-{team}-slot-1'
        team_post = {**post(donor_id), 'run_id': run_id, 'task_id': 'repeated-task',
                     'text': f'Team {team} finding'}
        posts.append(team_post)
        for slot in (1, 2):
            episode_id = f'team-{team}-slot-{slot}'
            audit, sample = fixture([team_post])
            audit[0].update(id=slot, run_id=run_id, episode_id=episode_id,
                            task_id='repeated-task')
            all_audit.extend(audit)
            sample.metadata = {'episode_id': episode_id, 'run_id': run_id,
                               'team': team, 'slot': slot, 'impossible_type': 'conflicting'}
            sample.id = 'repeated-task'
            sample.uuid = episode_id
            sample.scores = {}
            sample.model_usage = {}
            sample.limit = sample.error = None
            sample.working_time = 1.0
            path = run / f'team-{team}-slot-{slot}.eval'
            path.write_bytes(episode_id.encode())
            logs[path] = NS(status='success', samples=[sample], eval=NS(
                model='mockllm/model', config=Model(message_limit=90),
                metadata={'condition': 'board', 'cohort': 1}))
    # Same audit ID as a completed episode, but an unexported team's audit must survive.
    missing = {**all_audit[0], 'run_id': 'run-not-exported', 'episode_id': 'missing'}
    all_audit.append(missing)
    (run / 'board-final.json').write_text(json.dumps({'audit': all_audit, 'posts': posts}))
    monkeypatch.setattr(report, 'read_eval_log', lambda path, **kw: logs[path])
    out = tmp_path / 'report'
    manifest = report.generate_report(run, out)
    rows = json.loads((out / 'episodes.json').read_text())
    operations = json.loads((out / 'board-operations.json').read_text())
    edges = json.loads((out / 'exposure-edges.json').read_text())
    assert len(rows) == 4 and {r['task_id'] for r in rows} == {'repeated-task'}
    assert {(r['team'], r['slot']) for r in rows} == {(1, 1), (1, 2), (2, 1), (2, 2)}
    assert all(r['split'] == 'conflicting' for r in rows)
    assert len(operations) == 4 and all(o['delivery_confirmed'] for o in operations)
    assert {(o['run_id'], o['id']) for o in operations} == {('run-1', 1), ('run-1', 2), ('run-2', 1), ('run-2', 2)}
    assert len(edges) == 2
    for edge in edges:
        team = edge['team']
        assert edge['run_id'] == f'run-{team}'
        assert edge['author_episode_id'] == f'team-{team}-slot-1'
        assert edge['reader_episode_id'] == f'team-{team}-slot-2'
        assert edge['author_slot'] == 1 and edge['reader_slot'] == 2
        assert edge['text'] == f'Team {team} finding'
        assert edge['post_id'] == 1 and edge['audit_id'] == 2
    assert manifest['unmatched_audit_count'] == 1
    assert json.loads((out / 'unmatched-audit.json').read_text()) == [missing]
