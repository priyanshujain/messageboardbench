"""Summarize a fresh board export offline; no behavioral labels are inferred."""
import argparse
import json
from pathlib import Path
from statistics import median


def summarize(rows):
    fields = ['total_tokens', 'input_tokens', 'cache_read_tokens', 'cache_write_tokens',
              'output_tokens', 'reasoning_tokens', 'working_seconds', 'model_calls',
              'submit_tool_calls']
    return {
        'episodes': len(rows),
        'scorer_passes': sum(r['score'] in ('C', 1, 1.0) for r in rows),
        'errors': sum(r['error'] is not None for r in rows),
        'limits': sum(r['limit'] is not None for r in rows),
        'totals': {f: sum(r[f] or 0 for r in rows) if any(r[f] is not None for r in rows) else None
                   for f in fields},
        'median_working_seconds': median(r['working_seconds'] for r in rows) if rows else None,
        'publishing_episodes': sum(bool(r['published_post_ids']) for r in rows),
        'peer_receiving_episodes': sum(bool(r['peer_post_exposure_ids']) for r in rows),
        'feedback_call_episodes': sum(bool(r.get('feedback_tool_events')) for r in rows),
        'feedback_submitting_episodes': sum(bool(r.get('accepted_feedback_ids')) for r in rows),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads((args.export / 'episodes.json').read_text())
    operations = json.loads((args.export / 'board-operations.json').read_text())
    feedback_operations_path = args.export / 'feedback-operations.json'
    feedback_operations = (json.loads(feedback_operations_path.read_text())
                           if feedback_operations_path.is_file() else [])
    before = json.loads((args.run / 'budget-before.json').read_text())
    after = json.loads((args.run / 'budget-after.json').read_text())
    if before.get('provider') == 'clinepass':
        account_limitation = ('ClinePass account quota is unavailable from the '
                              'documented API; use episode usage and the Cline dashboard.')
    else:
        account_limitation = 'Account usage changes may include billing delay or other account activity.'
    result = {
        'all': summarize(rows),
        'by_condition': {c: summarize([r for r in rows if r['condition'] == c])
                         for c in sorted({r['condition'] for r in rows})},
        'by_condition_split': {f'{c}/{s}': summarize([r for r in rows if r['condition'] == c and r['split'] == s])
                               for c, s in sorted({(r['condition'], r['split']) for r in rows})},
        'board_reading_episodes': len({o['episode_id'] for o in operations
                                      if o['operation'] in {'board_read', 'read_team_messages', 'read_messages'}}),
        'public_posts': len(json.loads((args.export / 'public-posts.json').read_text())),
        'organizer_feedback_tool_calls': len(feedback_operations),
        'organizer_feedback_accepted_submissions': sum(
            bool(operation.get('response', {}).get('ok')) for operation in feedback_operations
        ),
        'budget_before': before, 'budget_after': after,
        'limitations': [
            'Scorer passes are not automatic behavioral labels.',
            'Reasoning tokens are a subset of output, not an additional cost.',
            'Input is uncached; cached input is reported separately and contributes to total.',
            'Working seconds are summed episode time, not experiment wall time.',
            account_limitation,
            'Small dependent development-task samples; descriptive comparisons only.',
        ],
    }
    with args.out.open('x') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
