"""Offline integrity/configuration validation of a fresh board export (no model calls)."""
import argparse
import hashlib
import json
from pathlib import Path

from inspect_ai.log import read_eval_log


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(run, export):
    manifest = json.loads((run / 'manifest.json').read_text())
    report = json.loads((export / 'manifest.json').read_text())
    episodes = json.loads((export / 'episodes.json').read_text())
    inputs = {x['sample']['metadata']['episode_id']: x for path in run.glob('phase-*-inputs.json')
              for x in json.loads(path.read_text())}
    checks = {}
    status_path = run / 'status.json'
    checks['run_completed'] = status_path.is_file() and json.loads(status_path.read_text()).get('status') == 'completed'
    expected = sorted((phase['team'], phase['cohort'], phase['condition'], plan['ids'][slot], plan['splits'][slot])
                      for phase in manifest['schedule'] for plan in manifest['team_plans'] if plan['team'] == phase['team']
                      for slot in range((phase['cohort']-1)*manifest['agents_per_cohort'], phase['cohort']*manifest['agents_per_cohort']))
    checks['matched_schedule'] = expected == sorted((e['team'], e['cohort'], e['condition'], e['task_id'], e['split']) for e in episodes)
    sources = []
    for entry in json.loads((run / 'source-snapshot/index.json').read_text()):
        sources.append({**entry, 'archived_hash_valid': sha(run / 'source-snapshot' / entry['archived']) == entry['sha256'],
                        'current_source_matches': Path(entry['source']).is_file() and sha(Path(entry['source'])) == entry['sha256']})
    checks['source_archive_hashes_valid'] = all(x['archived_hash_valid'] for x in sources)
    checks['planned_episode_count'] = len(episodes) == manifest['planned_episodes'] == len(inputs)
    checks['unique_identities'] = len({x['episode_id'] for x in episodes}) == len(episodes)
    checks['board_snapshot_hash_valid'] = sha(Path(report['board_snapshot_path'])) == report['board_sha256']
    checks['export_script_hash_valid'] = sha(Path(__file__).resolve().parents[1] / 'board_report.py') == report['report_script_sha256']
    checks['no_skipped_logs'] = not report['skipped_logs']
    checks['no_unmatched_audit'] = not json.loads((export / 'unmatched-audit.json').read_text())
    operations = json.loads((export / 'board-operations.json').read_text())
    checks['all_operations_delivery_confirmed'] = all(o['delivery_confirmed'] for o in operations)
    logs = {p['path']: p for p in report['logs']}
    sample_checks = []
    for row in episodes:
        path = Path(row['log_path'])
        log = read_eval_log(path, resolve_attachments=True)
        sample = next(s for s in log.samples if s.uuid == row['sample_uuid'])
        original = inputs[row['episode_id']]
        meta = original['sample']['metadata']
        cfg = log.eval.config.model_dump()
        generation = log.eval.model_generate_config.model_dump()
        c = {'log_hash_valid': sha(path) == logs[str(path)]['sha256'], 'log_success': log.status == 'success',
             'no_error': sample.error is None, 'no_limit': sample.limit is None,
             'model_exact': log.eval.model == manifest['model'],
             'strict_tools': log.eval.model_args.get('strict_tools') == manifest['strict_tools'],
             'task_id': str(sample.id) == str(original['sample']['id']),
             'tokens_balance': row['total_tokens'] == row['input_tokens'] + (row['cache_read_tokens'] or 0) + (row['cache_write_tokens'] or 0) + row['output_tokens'],
             'metadata_input_matches': all(sample.metadata.get(k) == meta[k] for k in ['test', 'test_patch', 'prompt', 'entry_point', 'condition', 'cohort', 'team', 'slot']),
             'instruction_and_availability_present': (any(m.role == 'user' and original['sample']['input'] == m.text for m in sample.messages) and any(original['availability'] in m.text for m in sample.messages[:2]))}
        for exported, field in [('input_tokens', 'input_tokens'), ('output_tokens', 'output_tokens'),
                                ('total_tokens', 'total_tokens'), ('cache_read_tokens', 'input_tokens_cache_read'),
                                ('cache_write_tokens', 'input_tokens_cache_write'), ('reasoning_tokens', 'reasoning_tokens')]:
            values = [getattr(u, field) for u in sample.model_usage.values()]
            expected_tokens = sum(v or 0 for v in values) if any(v is not None for v in values) else None
            c[exported + '_matches_log'] = row[exported] == expected_tokens
        for key in ['message_limit', 'token_limit', 'time_limit']:
            c[key] = cfg.get(key) == manifest[key]
        for key in ['temperature', 'reasoning_effort']:
            c[key] = generation.get(key) == manifest[key]
        final = json.loads((export / row['report_directory'] / 'final-artifacts.json').read_text())
        c['tests_not_modified'] = final.get('test_modified_ever') is False
        test_body = meta['test_patch'].replace('def check(', 'def test_func(')
        expected_test = f'from func import {meta["entry_point"]}\n\n{test_body}\n\nif __name__ == "__main__":\n    test_func({meta["entry_point"]})\n    print("All tests passed!")\n'
        c['final_test_bytes_match_input'] = final.get('submitted_artifacts', {}).get('test.py') == expected_test
        c['initial_scratch_empty'] = sample.metadata.get('scratch_initial_files') == {}
        for op in [o for o in operations if o['episode_id'] == row['episode_id']]:
            event = sample.events[op['event_index']]
            message = sample.messages[op['message_index']]
            c[f'audit_{op["id"]}_exact_delivery'] = (event.id == message.tool_call_id == op['tool_call_id'] and
                                                        json.loads(message.text) == op['response'])
        sample_checks.append({'episode_id': row['episode_id'], 'checks': c, 'config': cfg, 'generation': generation})
    failures = [{'scope': 'run', 'check': k} for k, v in checks.items() if not v]
    failures += [{'scope': x['episode_id'], 'check': k} for x in sample_checks for k, v in x['checks'].items() if not v]
    return {'run_checks': checks, 'sources': sources, 'samples': sample_checks, 'failures': failures,
            'totals': {k: sum(e[k] or 0 for e in episodes) for k in ['input_tokens', 'output_tokens', 'total_tokens', 'reasoning_tokens', 'cache_read_tokens']}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--export', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = validate(args.run.resolve(), args.export.resolve())
    with args.out.open('x') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print(json.dumps({'failures': result['failures'], 'totals': result['totals']}))
