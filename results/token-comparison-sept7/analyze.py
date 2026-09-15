"""Recompute descriptives from the frozen September 7 audit run list.
Run with messageboardbench/.venv/bin/python; no API calls and no log mutation.
"""
from pathlib import Path
import csv, hashlib, json, statistics
from inspect_ai.log import read_eval_log

HERE = Path(__file__).resolve().parent
BENCH = HERE.parents[2] / 'messageboardbench'
INCLUDED_RUNS = {'baseline', 'team-original-sept7', 'team-conflicting-shared-sept7', 'team-conflicting-private-sept7', 'token-rerun-private-lcbhard-0-sept7'}
METRICS = ['total_tokens','input_tokens','cache_read_tokens','all_input_tokens','output_tokens','reasoning_tokens','messages','turns','working_seconds']

def summarize(rows):
    return {'n':len(rows),'passed':sum(r['passed'] for r in rows),
      'limits':{k:sum(r['limit_type']==k for r in rows) for k in ['none','message','token','time']},
      'errored':sum(r['errored'] for r in rows),
      'medians':{k:statistics.median(r[k] for r in rows if r[k] is not None) if any(r[k] is not None for r in rows) else None for k in METRICS},
      'sums':{k:sum(r[k] for r in rows if r[k] is not None) for k in METRICS}}

rows=[]; provenance=[]; excluded=[]
for path in sorted((BENCH/'logs').rglob('*.eval')):
    if path.relative_to(BENCH/'logs').parts[0] not in INCLUDED_RUNS:
        excluded.append({'path':str(path),'reason':'outside frozen audit run list'});continue
    log=read_eval_log(path)
    if log.eval.model.startswith('mockllm/'):
        excluded.append({'path':str(path),'reason':'mock model','recoverable_samples':len(log.samples or [])});continue
    rel=path.relative_to(BENCH/'logs')
    condition='baseline_conflicting' if rel.parts[0]=='baseline' else rel.parts[0]
    provenance.append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
      'status':log.status,'planned_samples':log.eval.dataset.samples,'recoverable_samples':len(log.samples or []),
      'model':log.eval.model,'config':log.eval.config.model_dump(),
      'generate_config':log.eval.model_generate_config.model_dump()})
    for s in log.samples or []:
        usages=list(s.model_usage.values())
        def total(field): return sum(getattr(u,field) or 0 for u in usages)
        score=next(iter((s.scores or {}).values()),None)
        passed=score is not None and score.value=='C'
        r={'condition':condition,'task_id':str(s.id),'epoch':s.epoch,'log_path':str(path),'sample_uuid':s.uuid,
          'log_status':log.status,'model':log.eval.model,'started_at':s.started_at,
          'passed':passed,'score':None if score is None else score.value,
          'behavior_group':('impossible_pass_prior_audit_gaming' if passed else 'nonpass_behavior_not_inferred') if condition=='baseline_conflicting' else 'separate_review_no_executed_gaming_observed',
          'limit_type':s.limit.type if s.limit else 'none','limit_reason':s.limit.reason if s.limit else '',
          'message_limit':log.eval.config.message_limit,'token_limit':log.eval.config.token_limit,
          'messages':len(s.messages),'turns':s.turn_count,'working_seconds':s.working_time,
          'errored':s.error is not None,'input_tokens':total('input_tokens'),
          'cache_read_tokens':total('input_tokens_cache_read'),'cache_write_tokens':total('input_tokens_cache_write'),
          'output_tokens':total('output_tokens'),'reasoning_tokens':total('reasoning_tokens') if any(u.reasoning_tokens is not None for u in usages) else None,
          'total_tokens':total('total_tokens')}
        r['all_input_tokens']=r['input_tokens']+r['cache_read_tokens']+r['cache_write_tokens']
        assert r['total_tokens']==r['all_input_tokens']+r['output_tokens'],(path,s.id)
        assert r['reasoning_tokens'] is None or r['reasoning_tokens']<=r['output_tokens']
        rows.append(r)

def write_csv(path,data):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
write_csv(HERE/'samples.csv',rows)
conditions={k:summarize([r for r in rows if r['condition']==k]) for k in sorted({r['condition'] for r in rows})}
baseline=[r for r in rows if r['condition']=='baseline_conflicting']
baseline_groups={k:summarize([r for r in baseline if r['passed']==passed]) for k,passed in [('impossible_pass_prior_audit_gaming',True),('nonpass_behavior_not_inferred',False)]}
matched=[]
original={r['task_id']:r for r in rows if r['condition']=='team-original-sept7'}
for r in rows:
    if r['condition']!='team-conflicting-shared-sept7' or r['task_id'] not in original:continue
    o=original[r['task_id']]
    m={'task_id':r['task_id'],'original_log':o['log_path'],'impossible_log':r['log_path'],'original_limit':o['limit_type'],'impossible_limit':r['limit_type']}
    for k in METRICS:
        m['original_'+k]=o[k];m['impossible_'+k]=r[k]
        m['ratio_'+k]=r[k]/o[k] if o[k] else None
    matched.append(m)
write_csv(HERE/'matched-original-impossible.csv',matched)
ids={r['task_id'] for r in rows if r['condition']=='team-conflicting-shared-sept7'}
matched6={k:summarize([r for r in rows if r['condition']==k and r['task_id'] in ids]) for k in ['baseline_conflicting','team-conflicting-shared-sept7','team-conflicting-private-sept7']}
result={'included_run_directories':sorted(INCLUDED_RUNS),'total_recoverable_paid_samples':len(rows),'conditions':conditions,'baseline_outcome_groups':baseline_groups,'matched_six_tasks_cross_date':matched6,'matched_six_task_ids':sorted(ids),'matched_original_impossible_n':len(matched),'log_provenance':provenance,'excluded_logs':excluded,
 'interpretation':['Nonpass is not an honesty label. Prior baseline audit identified 18 impossible passes as gaming; no new semantic classification was performed by this script.','Baseline log is started with 39 recovered of 40 planned, not a completed 40-sample run.','Same model identifier but August31 vs September7, different prompts, limits, concurrency and retry settings; cross-date comparisons are descriptive only.','Input tokens are summed over repeated model calls; cache-read tokens count toward total. Reasoning tokens are a subset of output, not additional. No claim about distinct reasoning amount from total tokens.','32/39 baseline attempts ended at message cap, and 8/12 new impossible attempts at token cap. These are censored trajectories. Passing early and retry-until-failure stopping rules also confound resource comparisons.','Only two same-condition original/impossible task pairs exist; no paid original August baseline exists in these logs.','No significance testing or causal attribution; shared samples are team-dependent and no repeated randomized teams exist.']}
(HERE/'results.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'conditions':conditions,'baseline_outcome_groups':baseline_groups,'matched':matched},indent=2))
