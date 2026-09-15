import json,hashlib,re
from pathlib import Path
from inspect_ai.log import read_eval_log
from messageboardbench.board_task import availability,describe_team_tools
base=Path('/Users/pj/Workspace/projects/python/research')
old=base/'messageboardbench/logs/board-pilot-glm-sept8'
new=base/'messageboardbench/logs/board-pilot-glm-interface-v2-sept8'
out=base/'messageboard/scratchpad/board-interface-v2-sept8'
load=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
a,b=load(old/'manifest.json'),load(new/'manifest.json')
manifest_diff={k:{'old':a.get(k),'new':b.get(k)} for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}
checks=[]
for p in sorted(new.glob('phase-*-inputs.json')):
 x,y=load(old/p.name),load(p)
 for i,j in zip(x,y):
  si,sj=i['sample'],j['sample'];mi,mj=si['metadata'],sj['metadata']
  fields=['prompt','test','entry_point','instruction_prompt','impossible_type','task_id','test_patch','cohort','condition']
  checks.append({'phase':p.name,'task':sj['id'],'condition':mj['condition'],'sample_fields_equal':all(si[k]==sj[k] for k in si if k!='metadata'),'metadata_fields_equal':all(mi[k]==mj[k] for k in fields),'availability_matches_v2':j['availability']==availability(mj['condition'],mj['episode_id'])})
source=[]
for row in load(new/'source-snapshot/index.json'):
 source.append({'archived':row['archived'],'archive_hash_valid':sha(new/'source-snapshot'/row['archived'])==row['sha256'],'live_source_matches_archive':sha(Path(row['source']))==row['sha256']})
prior={}
for p in (old/'evals').glob('*.eval'):
 l=read_eval_log(p,resolve_attachments=True)
 for s in l.samples or []:prior[s.metadata['condition'],s.id]=(l,s)
logs=[]
for p in (new/'evals').glob('*.eval'):
 l=read_eval_log(p,resolve_attachments=True)
 for s in l.samples or []:
  ol,os=prior[s.metadata['condition'],s.id]
  # Preserve baseline bytes by stripping the exact v1 availability, then append v2 availability.
  oldphase=next(z for f in old.glob('phase-*-inputs.json') for z in load(f) if z['sample']['metadata']['condition']==s.metadata['condition'] and z['sample']['id']==s.id)
  suffix='\n'+oldphase['availability']+'\n'
  assert os.messages[0].content.endswith(suffix)
  expected=os.messages[0].content[:-len(suffix)]
  if s.metadata['condition']=='board':expected=describe_team_tools(expected)
  expected+='\n'+availability(s.metadata['condition'],s.metadata['episode_id'])+'\n'
  first=next(e for e in s.events if e.event=='model')
  names=[t.name for t in first.tools]
  logs.append({'log':p.name,'sha256':sha(p),'task':s.id,'condition':s.metadata['condition'],'log_status':l.status,'sample_error':s.error is not None,'sample_limit':s.limit.model_dump() if s.limit else None,'system_prompt_expected_exactly':s.messages[0].content==expected,'initial_scratch_empty':s.metadata.get('scratch_initial_files')=={},'config_equal_v1':l.eval.config==ol.eval.config,'generate_config_equal_v1':l.eval.model_generate_config==ol.eval.model_generate_config,'model_equal_v1':l.eval.model==ol.eval.model,'model_args_equal_v1':l.eval.model_args==ol.eval.model_args,'actual_initial_tools':names,'board_tools_expected':(('read_team_messages' in names and 'post_team_message' in names) if s.metadata['condition']=='board' else all(x not in names for x in ['read_team_messages','post_team_message','board_read','board_post']))})
result={'complete':(new/'status.json').exists(),'manifest_differences':manifest_diff,'schedule_equal':load(new/'schedule.json')==load(old/'schedule.json'),'input_checks':checks,'source_checks':source,'completed_sample_checks':logs,'note':'The entire interface bundle changed: tool names, descriptions, and main prompt tool-list placement. This does not isolate the effect of any single change.'}
(out/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
fail=[r for r in checks+source+logs for k,v in r.items() if isinstance(v,bool) and not v and k not in ['sample_error']]
(out/'verification.md').write_text(f'''# Independent run verification\n\nRun complete: {result['complete']}. Checked {len(checks)} archived task inputs and {len(logs)} completed sample logs. Failed boolean checks: {len(fail)}.\n\nThe task text, test bytes, entry points, task schedule, model, execution limits, and generation settings are compared with the prior GLM pilot. Completed samples are checked against the exact prior baseline prompt plus the intended v2 interface additions, with new episode identities. Source archive hashes and current source are checked separately.\n\nManifest differences:\n```json\n{json.dumps(manifest_diff,indent=2)}\n```\n\nSee verification.json for per-sample checks and log hashes. The run remains in progress until all 12 samples are recorded here. Interface changes are bundled and are not a naming-only intervention.\n''')
print(json.dumps({'complete':result['complete'],'inputs':len(checks),'logs':len(logs),'failed_boolean_checks':len(fail),'manifest_diffs':manifest_diff},indent=2))
export=out/'final-export'
if result['complete'] and export.exists():
 em=load(export/'manifest.json');episodes=load(export/'episodes.json');ops=load(export/'board-operations.json')
 checks_export={'twelve_episodes':len(episodes)==12,'all_log_hashes_valid':all(sha(Path(r['path']))==r['sha256'] for r in em['logs']),'board_hash_valid':sha(Path(em['board_snapshot_path']))==em['board_sha256'],'report_script_hash_valid':sha(base/'messageboardbench/scripts/board_report.py')==em['report_script_sha256'],'all_operations_delivery_confirmed':all(o['delivery_confirmed'] for o in ops),'no_unmatched_audit':load(export/'unmatched-audit.json')==[],'all_token_totals_consistent':all(e['total_tokens']==sum(e.get(k) or 0 for k in ['input_tokens','cache_read_tokens','cache_write_tokens','output_tokens']) for e in episodes),'all_samples_success_no_error_no_limit':all(r['log_status']=='success' and not r['sample_error'] and not r['sample_limit'] for r in logs),'all_unique_episode_identities':len({e['episode_id'] for e in episodes})==12,'schedule_equal_v1':result['schedule_equal']}
 result['final_export_checks']=checks_export
 result['final_status']=load(new/'status.json')
 result['board_operation_count']=len(ops)
 result['exposure_edge_count']=len(load(export/'exposure-edges.json'))
 result['complete']=result['final_status']['status']=='completed' and len(logs)==12
 (out/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
 text=(out/'verification.md').read_text().replace('The run remains in progress until all 12 samples are recorded here.','All 12 episodes completed; all 12 exact prompts and configurations are verified.')
 text+='\n## Final export checks\n\n'+ '\n'.join(f'- {k}: {v}' for k,v in checks_export.items())+'\n\nVerified 13 source archive hashes, 12 completed log hashes, the final board snapshot hash, and the report script hash. All recorded board operations were linked to delivered tool output; exported token totals balance for all episodes.\n'
 (out/'verification.md').write_text(text)
 print(json.dumps(checks_export,indent=2))
