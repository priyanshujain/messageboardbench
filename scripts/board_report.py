"""Offline board-pilot evidence export. No semantic/intent classification.

Usage: .venv/bin/python scripts/board_report.py --run logs/RUN --out reports/FRESH
All message/event indices are zero-based and refer to the original eval sample.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any
from inspect_ai.log import read_eval_log


BOARD_POST_OPERATIONS = {'board_post', 'post_team_message', 'send_message'}
BOARD_READ_OPERATIONS = {'board_read', 'read_team_messages', 'read_messages'}


def dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + '\n')


def plain_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    pieces = []
    for block in content or []:
        d = block.model_dump() if hasattr(block, 'model_dump') else block
        if d.get('type') == 'text':
            pieces.append(d.get('text', ''))
        elif d.get('type') == 'reasoning':
            # Never serialize provider internal/signature fields or redacted payloads.
            if d.get('redacted'):
                pieces.append('[encrypted/redacted reasoning omitted]')
            else:
                pieces.append('[reasoning]\n' + d.get('reasoning', ''))
        else:
            pieces.append(f"[{d.get('type', 'nontext')} omitted]")
    return '\n'.join(pieces)


def as_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None
    if isinstance(value, list):
        return as_json(plain_content(value))
    return value


def index_messages(sample) -> list[dict]:
    return [{'message_index': i, 'message_id': getattr(m, 'id', None),
             'role': m.role, 'content': plain_content(m.content),
             'tool_call_id': getattr(m, 'tool_call_id', None),
             'tool_calls': [{'id': t.id, 'function': t.function, 'arguments': t.arguments}
                            for t in getattr(m, 'tool_calls', None) or []]}
            for i, m in enumerate(sample.messages)]


def link_board_operations(audit: list[dict], sample) -> tuple[list[dict], list[dict]]:
    """Join host audit to actual returned tool messages; self/empty reads give no edges.

    Matching is one-to-one in audit/event order using operation and complete JSON
    response equality. Audit alone proves server execution, not response delivery.
    """
    events = [(i, e) for i, e in enumerate(sample.events)
              if e.event == 'tool' and e.function in BOARD_POST_OPERATIONS | BOARD_READ_OPERATIONS]
    messages = index_messages(sample)
    used = set()
    linked, edges = [], []
    for a in sorted(audit, key=lambda a: a['id']):
        response = json.loads(a['response_json'])
        item = {**a, 'request': json.loads(a['request_json']), 'response': response,
                'event_index': None, 'message_index': None, 'tool_call_id': None,
                'delivery_confirmed': False, 'next_model_event_index': None}
        for i, e in events:
            if a['operation'] in {'board_read', 'read_team_messages'}:
                defaults = {'after_id': None, 'limit': 20}
            elif a['operation'] == 'read_messages':
                defaults = {'intent_type': None, 'limit': 20, 'offset': 0}
            elif a['operation'] in {'board_post', 'post_team_message'}:
                defaults = {'reply_to': None}
            else:
                defaults = {}
            args = {**defaults, **(e.arguments or {})}
            if i in used or e.function != a['operation'] or args != item['request'] or as_json(e.result) != response:
                continue
            used.add(i)
            item.update(event_index=i, tool_call_id=e.id)
            for m in messages:
                if m['role'] == 'tool' and m['tool_call_id'] == e.id and as_json(m['content']) == response:
                    item.update(message_index=m['message_index'], delivery_confirmed=True)
                    break
            item['next_model_event_index'] = next((j for j in range(i + 1, len(sample.events))
                                                    if sample.events[j].event == 'model'), None)
            break
        linked.append(item)
        if a['operation'] not in BOARD_READ_OPERATIONS or not response.get('ok') or not item['delivery_confirmed']:
            continue
        for post in response.get('posts', []):
            if post['episode_id'] == a['episode_id']:
                continue
            edges.append({'run_id': a['run_id'], 'author_episode_id': post['episode_id'],
                          'reader_episode_id': a['episode_id'], 'post_id': post['id'],
                          'author_task_id': post['task_id'], 'reader_task_id': a['task_id'],
                          'audit_id': a['id'], 'event_index': item['event_index'],
                          'message_index': item['message_index'], 'tool_call_id': item['tool_call_id'],
                          'next_model_event_index': item['next_model_event_index'],
                          'text': post['text'], 'interpretation': 'peer text returned; adoption not inferred'})
    return linked, edges


def link_feedback_operations(audit: list[dict], sample) -> list[dict]:
    """Link private host receipts to the exact submit_feedback tool results."""
    events = [(index, event) for index, event in enumerate(sample.events)
              if event.event == 'tool' and event.function == 'submit_feedback']
    messages = index_messages(sample)
    used = set()
    linked = []
    for entry in sorted(audit, key=lambda row: row['id']):
        response = json.loads(entry['response_json'])
        item = {**entry, 'operation': 'submit_feedback',
                'request': json.loads(entry['request_json']), 'response': response,
                'event_index': None, 'message_index': None, 'tool_call_id': None,
                'delivery_confirmed': False}
        for index, event in events:
            if (index in used or (event.arguments or {}) != item['request']
                    or as_json(event.result) != response):
                continue
            used.add(index)
            item.update(event_index=index, tool_call_id=event.id)
            for message in messages:
                if (message['role'] == 'tool' and message['tool_call_id'] == event.id
                        and as_json(message['content']) == response):
                    item.update(message_index=message['message_index'], delivery_confirmed=True)
                    break
            break
        linked.append(item)
    return linked


def artifact_record(score, event_index=None, intermediate=None) -> dict:
    meta = score.metadata or {}
    return {'event_index': event_index, 'intermediate': intermediate,
            'score': score.value, 'explanation': score.explanation,
            'submitted_artifacts': meta.get('submitted_artifacts', {}),
            'scratch_files': meta.get('scratch_files', {}),
            'test_modified_this_attempt': meta.get('test_modified_this_attempt'),
            'test_modified_ever': meta.get('test_modified_ever'),
            'model_patch': meta.get('model_patch'),
            'changed_paths_before_scoring': meta.get('changed_paths_before_scoring'),
            'modified_test_paths': meta.get('modified_test_paths'),
            'strict_target_statuses': meta.get('strict_target_statuses'),
            'strict_test_exit_code': meta.get('strict_test_exit_code')}


def write_csv(path: Path, rows: list[dict], fields=None) -> None:
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()})


def generate_report(run: Path, out: Path, board_snapshot: Path | None = None) -> dict:
    run = run.resolve()
    if out.exists():
        raise FileExistsError(f'Report output must be fresh: {out}')
    board_path = board_snapshot.resolve() if board_snapshot is not None else run / 'board-final.json'
    board = json.loads(board_path.read_text())
    feedback_path = run / 'feedback-final.json'
    feedback = json.loads(feedback_path.read_text()) if feedback_path.is_file() else {
        'submissions': [], 'audit': []
    }
    paths = sorted(run.rglob('*.eval'))
    if not paths:
        raise ValueError('No eval logs found')
    out.mkdir(parents=True)
    episodes, edges, operations, feedback_operations = [], [], [], []
    annotations, provenance, skipped = [], [], []
    seen = set()
    for path in paths:
        log = read_eval_log(path, resolve_attachments=True)
        if log.status not in {'success', 'error', 'cancelled'}:
            skipped.append({'path': str(path), 'status': log.status, 'reason': 'not completed'})
            continue
        provenance.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                           'status': log.status, 'model': log.eval.model,
                           'config': log.eval.config.model_dump(), 'metadata': log.eval.metadata})
        for sample in log.samples or []:
            meta = {**(log.eval.metadata or {}), **(sample.metadata or {})}
            episode_id = meta.get('episode_id')
            if not episode_id or episode_id in seen:
                raise ValueError(f'Missing or duplicate episode_id: {episode_id}')
            seen.add(episode_id)
            # Never use model-provided paths as host output locations.
            destination = out / f'episode-{len(episodes) + 1:03d}'
            destination.mkdir()
            indexed = index_messages(sample)
            dump(destination / 'messages.json', indexed)
            (destination / 'messages.txt').write_text('\n\n'.join(
                f"MESSAGE {m['message_index']} [{m['role']}] id={m['message_id']} tool_call_id={m['tool_call_id']}\n"
                + m['content'] + ('\nTOOL CALLS: ' + json.dumps(m['tool_calls'], ensure_ascii=False) if m['tool_calls'] else '')
                for m in indexed))
            relevant = [a for a in board.get('audit', []) if a['episode_id'] == episode_id and a['run_id'] == meta.get('run_id')]
            linked, sample_edges = link_board_operations(relevant, sample)
            for operation in linked:
                operation.update(team=meta.get('team', 1), slot=meta.get('slot'))
            for edge in sample_edges:
                edge.update(team=meta.get('team', 1), reader_slot=meta.get('slot'))
            operations.extend(linked); edges.extend(sample_edges)
            dump(destination / 'board-operations.json', linked)
            feedback_relevant = [entry for entry in feedback.get('audit', [])
                                 if entry['episode_id'] == episode_id]
            linked_feedback = link_feedback_operations(feedback_relevant, sample)
            feedback_operations.extend(linked_feedback)
            dump(destination / 'feedback-operations.json', linked_feedback)
            score = next(iter((sample.scores or {}).values()), None)
            attempts = [artifact_record(e.score, i, e.intermediate)
                        for i, e in enumerate(sample.events) if e.event == 'score']
            dump(destination / 'scorer-artifacts.json', attempts)
            final = artifact_record(score) if score else {}
            dump(destination / 'final-artifacts.json', final)
            for name in ('func.py', 'test.py'):
                content = final.get('submitted_artifacts', {}).get(name)
                if isinstance(content, str):
                    (destination / ('final-' + name)).write_text(content)
            if isinstance(final.get('model_patch'), str):
                (destination / 'final-model.patch').write_text(final['model_patch'])
            usage = list(sample.model_usage.values())
            def tokens(field):
                values = [getattr(u, field) for u in usage]
                return sum(v or 0 for v in values) if any(v is not None for v in values) else None
            row = {'episode_id': episode_id, 'run_id': meta.get('run_id'), 'condition': meta.get('condition'),
                   'team': meta.get('team', 1), 'slot': meta.get('slot'),
                   'cohort': meta.get('cohort'), 'split': meta.get('split', meta.get('impossible_type')),
                   'task_id': str(sample.id), 'model': log.eval.model, 'log_path': str(path),
                   'sample_uuid': sample.uuid, 'report_directory': destination.name,
                   'score': score.value if score else None,
                   'limit': sample.limit.model_dump() if sample.limit else None,
                   'error': str(sample.error) if sample.error else None,
                   'total_tokens': tokens('total_tokens'), 'input_tokens': tokens('input_tokens'),
                   'cache_read_tokens': tokens('input_tokens_cache_read'),
                   'cache_write_tokens': tokens('input_tokens_cache_write'),
                   'output_tokens': tokens('output_tokens'), 'reasoning_tokens': tokens('reasoning_tokens'),
                   'model_calls': sum(e.event == 'model' for e in sample.events),
                   'messages': len(sample.messages),
                   'submit_tool_calls': sum(e.event == 'tool' and e.function == 'submit' for e in sample.events),
                   'score_events': len(attempts), 'working_seconds': sample.working_time,
                   'scratch_files': list(final.get('scratch_files', {})),
                   'test_modified_ever': final.get('test_modified_ever'),
                   'published_post_ids': [a['response']['post']['id'] for a in linked
                                          if a['operation'] in BOARD_POST_OPERATIONS and a['response'].get('ok')],
                   'peer_post_exposure_ids': [e['post_id'] for e in sample_edges],
                   'feedback_tool_events': sum(e.event == 'tool' and e.function == 'submit_feedback'
                                               for e in sample.events),
                   'feedback_host_audited_calls': len(linked_feedback),
                   'accepted_feedback_ids': [a['response']['receipt_id'] for a in linked_feedback
                                             if a['response'].get('ok')]}
            episodes.append(row)
            for behavior in ['gaming', 'publication', 'exposure', 'adoption', 'rejection', 'correction']:
                annotations.append({'episode_id': episode_id, 'behavior': behavior, 'label': '',
                                    'message_indices': '', 'event_indices': '', 'audit_ids': '',
                                    'post_ids': '', 'source_episode_id': '', 'evidence': '', 'reviewer': ''})
    episode_lookup = {(e['run_id'], e['episode_id']): e for e in episodes}
    for edge in edges:
        author = episode_lookup.get((edge['run_id'], edge['author_episode_id']))
        edge['author_slot'] = author['slot'] if author else None
    dump(out / 'episodes.json', episodes)
    if episodes:
        write_csv(out / 'episodes.csv', episodes)
        write_csv(out / 'annotations.csv', annotations)
    dump(out / 'exposure-edges.json', edges)
    dump(out / 'board-operations.json', operations)
    dump(out / 'public-posts.json', board.get('posts', []))
    unmatched = [a for a in board.get('audit', []) if not any(a['id'] == o['id'] and a['run_id'] == o['run_id'] for o in operations)]
    dump(out / 'unmatched-audit.json', unmatched)
    dump(out / 'feedback-operations.json', feedback_operations)
    dump(out / 'organizer-feedback-submissions.json', feedback.get('submissions', []))
    unmatched_feedback = [entry for entry in feedback.get('audit', [])
                          if not any(entry['id'] == linked['id']
                                     for linked in feedback_operations)]
    dump(out / 'unmatched-feedback-audit.json', unmatched_feedback)
    manifest = {'run': str(run), 'episodes': len(episodes), 'exposure_edges': len(edges),
                'board_sha256': hashlib.sha256(board_path.read_bytes()).hexdigest(),
                'board_snapshot_path': str(board_path),
                'explicit_board_snapshot': board_snapshot is not None,
                'report_scope': 'partial snapshot / completed logs only' if board_snapshot is not None or skipped else 'final snapshot / completed logs only',
                'report_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'logs': provenance, 'skipped_logs': skipped,
                'unlinked_operation_count': sum(not o['delivery_confirmed'] for o in operations),
                'unmatched_audit_count': len(unmatched),
                'feedback_submission_count': len(feedback.get('submissions', [])),
                'feedback_operation_count': len(feedback_operations),
                'unmatched_feedback_audit_count': len(unmatched_feedback),
                'limitations': ['Zero-based original sample message/event indices.',
                  'Edges require successful peer-post responses present in tool messages; not proof of attention, adoption or collusion.',
                  'Host audit without a matched delivered tool response is retained but creates no exposure edge.',
                  'Repeated reads create repeated exposure edges; aggregate unique post IDs separately.',
                  'Model calls count model events, not provider-internal HTTP retries.',
                  'Reasoning is a subset of output; cached/repeated input contributes to total.',
                  'Scorer artifacts include intermediate and final grading events; they are not necessarily unique submissions.',
                  'Final source and scratch snapshots retain the scorer capture bounds and may be truncated.',
                  'No automatic gaming or intent labels are assigned.']}
    dump(out / 'manifest.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--board-snapshot', type=Path, help='Explicit interim or final board JSON; labels the report as a partial snapshot')
    args = parser.parse_args()
    result = generate_report(args.run, args.out, args.board_snapshot)
    print(json.dumps({k: result[k] for k in ('episodes', 'exposure_edges', 'unlinked_operation_count', 'unmatched_audit_count')}))


if __name__ == '__main__':
    main()
