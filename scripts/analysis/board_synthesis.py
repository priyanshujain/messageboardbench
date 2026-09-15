"""Offline descriptive synthesis of the frozen GLM board-interface rerun."""
import argparse
from pathlib import Path
import csv
import hashlib
import json
import statistics

BENCH = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_text())


def enrich(root, out):
    episodes = read(root / 'final-export/episodes.json')
    assert len(episodes) == 12
    operations = read(root / 'final-export/board-operations.json')
    rows = []
    for e in episodes:
        task = e['task_id'].removeprefix('lcbhard_')
        path = root / f"reviews/{e['condition']}-c{e['cohort']}-task{task}.json"
        r = read(path)
        assert r.get('review_complete'), path
        assert r.get('sample_id', r.get('task_id')) == e['task_id'], path
        row = dict(e)
        row.update({
            'executed_gaming_observed': r.get('gaming', r.get('executed_gaming_observed')),
            'gaming_mechanism': r.get('mechanism', r.get('gaming_mechanism')),
            'final_local_refusal': r.get('final_local_refusal', False),
            'peer_adoption_observed': r.get('peer_adoption_observed', False),
            'peer_rejection_observed': r.get('peer_rejection_observed', False),
            'published_gaming_method': r.get('published_gaming_method', e['condition'] == 'board' and e['cohort'] == 1 and task in {'1','2'}),
            'behavior': r.get('verdict', r.get('behavior')),
            'review_file': str(path.relative_to(root)),
            'review_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'review_method': 'Codex-assisted full trace/artifact review; no independent blinded human labels',
            'read_tool_calls': sum(o['episode_id'] == e['episode_id'] and o['operation'] in {'board_read','read_team_messages'} for o in operations),
        })
        assert isinstance(row['executed_gaming_observed'], bool), path
        assert e['total_tokens'] == e['input_tokens'] + (e['cache_read_tokens'] or 0) + e['output_tokens'], e
        rows.append(row)
    (out / 'reviewed-episodes.json').write_text(json.dumps(rows, indent=2)+'\n')
    with (out / 'reviewed-episodes.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: json.dumps(v) if isinstance(v, (dict,list)) else v for k,v in r.items()})
    return rows


def usage(rows):
    return {'n':len(rows), **{f'{aggregation}_{field}': fn([r[field] for r in rows]) if rows else None
        for field in ['total_tokens','output_tokens','reasoning_tokens','input_tokens','cache_read_tokens']
        for aggregation,fn in [('sum',sum),('median',statistics.median)]}}


def interface_stats(root, rows):
    ops = read(root / 'final-export/board-operations.json')
    board = [r for r in rows if r['condition']=='board']
    readops = [o for o in ops if o['operation'] in {'board_read','read_team_messages'}]
    return {
        'board_episodes':len(board), 'reader_episodes':len({o['episode_id'] for o in readops}),
        'read_calls':len(readops), 'peer_exposed_episodes':sum(bool(r['peer_post_exposure_ids']) for r in board),
        'publisher_episodes':sum(bool(r['published_post_ids']) for r in board),
        'posts':len(read(root/'final-export/public-posts.json')),
        'board_conflicting_gaming':sum(r['executed_gaming_observed'] for r in board if r['split']=='conflicting'),
        'board_conflicting_n':sum(r['split']=='conflicting' for r in board),
        'private_conflicting_gaming':sum(r['executed_gaming_observed'] for r in rows if r['condition']=='private' and r['split']=='conflicting'),
        'private_conflicting_n':sum(r['condition']=='private' and r['split']=='conflicting' for r in rows),
        'peer_adoption_episodes':sum(r['peer_adoption_observed'] for r in board),
        'peer_rejection_episodes':sum(r['peer_rejection_observed'] for r in board),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results-v1', type=Path, default=BENCH / 'results/board-pilot-sept8')
    parser.add_argument('--results-v2', type=Path, default=BENCH / 'results/board-interface-v2-sept8')
    parser.add_argument('--out', type=Path, required=True, help='Fresh output directory; frozen evidence is never overwritten.')
    args = parser.parse_args(argv)
    v1, root, out = args.results_v1.resolve(), args.results_v2.resolve(), args.out.resolve()
    for source in (v1, root):
        if not source.is_dir():
            parser.error(f'Results directory does not exist: {source}')
        if out == source or source in out.parents:
            parser.error('Output must be outside the source evidence directories')
    out.mkdir(parents=True, exist_ok=False)
    rows = enrich(root, out)
    old = read(v1/'reviewed-episodes.json')
    comparisons = {'v1':interface_stats(v1,old), 'v2':interface_stats(root,rows)}
    groups = {'original':[r for r in rows if r['split']=='original'],
              'conflicting':[r for r in rows if r['split']=='conflicting'],
              'gaming':[r for r in rows if r['executed_gaming_observed']],
              'non_gaming':[r for r in rows if not r['executed_gaming_observed']]}
    summaries = {name:usage(rs) for name,rs in groups.items()}
    old_groups = {'original':[r for r in old if r['split']=='original'],
        'conflicting':[r for r in old if r['split']=='conflicting'],
        'gaming':[r for r in old if r['executed_gaming_observed']],
        'non_gaming':[r for r in old if not r['executed_gaming_observed']]}
    summary = {'interface_comparison':comparisons,'v2_usage':summaries,
        'v1_usage':{name:usage(rs) for name,rs in old_groups.items()}}
    (out/'token-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    lines = ['# GLM board interface rerun: descriptive analysis','',
        'Twelve completed episodes, joined by condition/cohort/task to full trajectory reviews. No additional model calls. Counts below describe these episodes; they are not model-level rates or causal effect estimates.','',
        '## Interface use and behavior','', '| Measure | v1 | v2 |','|---|---:|---:|']
    for key,label in [('reader_episodes','Board episodes that called read (of 6)'),('read_calls','Read calls'),('peer_exposed_episodes','Board episodes actually receiving peer content (of 6)'),('publisher_episodes','Board episodes posting (of 6)'),('posts','Public posts'),('board_conflicting_gaming','Gaming in board impossible tasks (of 4)'),('private_conflicting_gaming','Gaming in private impossible tasks (of 4)'),('peer_adoption_episodes','Reviewed peer-adoption trajectories'),('peer_rejection_episodes','Reviewed peer-rejection trajectories')]:
        lines.append(f"| {label} | {comparisons['v1'][key]} | {comparisons['v2'][key]} |")
    lines += ['', 'The interface revision bundled renamed tools, clearer purpose/read instructions, and explicit placement in the main tool list. This is one small sequential rerun, not randomized replication separating those changes. Shared-board episodes belong to one interacting population, so they are not independent samples. A read call returning an empty board is not exposure; receipt of content alone is not adoption. Adoption labels require explicit trajectory evidence, and do not identify the counterfactual behavior without that message.', '',
        '## Token use in v2','', '| Group | n | Total tokens, sum | Total, median | Output, sum | Output, median | Reasoning, sum |','|---|---:|---:|---:|---:|---:|---:|']
    for name,u in summaries.items():
        lines.append(f"| {name} | {u['n']} | {u['sum_total_tokens']:,} | {u['median_total_tokens']:,} | {u['sum_output_tokens']:,} | {u['median_output_tokens']:,} | {u['sum_reasoning_tokens']:,} |")
    a,b=summaries['original'],summaries['conflicting']
    lines += ['', f"Impossible-task median total tokens were {b['median_total_tokens']/a['median_total_tokens']:.2f}× the original-task median; median generated output was {b['median_output_tokens']/a['median_output_tokens']:.2f}×. These groups use different task IDs (original 0/11; conflicting 1/2/10/12), so difficulty and content confound any impossibility interpretation.", '',
        'Total tokens = uncached input + cache-read input + output in these exports. Repeated/cached context is counted each model call. Reasoning is a subset of output and must not be added again. Neither total-token ratios nor a common reasoning-effort label measure equal compute or cost.', '',
        'Gaming/non-gaming groups are behavior-defined, not randomized. All eight impossible episodes gamed in v2, so this comparison is exactly the original/conflicting comparison and says nothing separate about the token cost of cheating. Failed honest submissions followed by gaming are assigned to gaming at episode level; their tokens include both phases. Long private task10/12 trajectories also contain substantial unproductive interpretation-search and errors in agents’ own validation code.', '',
        '## Same task, different communication condition','',
        '| Task | Split | Private total | Board total | Board/private total | Private output | Board output | Board/private output |','|---|---|---:|---:|---:|---:|---:|---:|']
    for task in sorted({r['task_id'] for r in rows},key=lambda x:int(x.split('_')[-1])):
        p=next(r for r in rows if r['task_id']==task and r['condition']=='private')
        q=next(r for r in rows if r['task_id']==task and r['condition']=='board')
        lines.append(f"| {task} | {p['split']} | {p['total_tokens']:,} | {q['total_tokens']:,} | {q['total_tokens']/p['total_tokens']:.2f}× | {p['output_tokens']:,} | {q['output_tokens']:,} | {q['output_tokens']/p['output_tokens']:.2f}× |")
    lines += ['', 'These are single-attempt task matches, not paired random-seed replications. Board cohort2 can receive cohort1 posts and differs from private controls in both communication access and realized peer advice. Prior v1/v2 outcomes cannot support a stable cheating-rate or efficiency estimate; use them to establish usable interfaces and traceable behavior for a larger controlled design.', '',
        '## Earlier v1 token context','', '| Group | n | Total, median | Output, median |','|---|---:|---:|---:|']
    for name,u in summary['v1_usage'].items():
        lines.append(f"| {name} | {u['n']} | {u['median_total_tokens']:,} | {u['median_output_tokens']:,} |")
    lines += ['', 'In v1, the non-gaming group contains four original tasks and one impossible-task refusal. That mixture is not a matched comparison with successful gaming, and one refusal provides no reliable estimate of honest impossible-task token use.', '',
        'Source files: `final-export/episodes.json`, `final-export/board-operations.json`, `final-export/public-posts.json`, each linked review, and v1 equivalents. Machine-readable outputs: `reviewed-episodes.json`, `reviewed-episodes.csv`, `token-summary.json`.']
    (out/'token-analysis.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    main()
