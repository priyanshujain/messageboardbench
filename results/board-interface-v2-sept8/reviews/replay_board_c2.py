"""Offline replay of reviewed v2 board artifacts inside isolated Docker only."""
import hashlib
import json
from pathlib import Path
import subprocess
import uuid
from inspect_ai.log import read_eval_log

ROOT = Path(__file__).resolve().parent
RUN = ROOT.parents[3] / 'messageboardbench/logs/board-pilot-glm-interface-v2-sept8'

def replay(task, probe):
    path = next((RUN/'evals').glob(f'*board-c2-p{task-9}*'))
    log = read_eval_log(path, resolve_attachments=True)
    assert log.status == 'success'
    sample = log.samples[0]
    source = sample.scores['scratch_scorer'].metadata['submitted_artifacts']['func.py']
    directory = ROOT/f'board-c2-task{task}-probe'
    directory.mkdir(exist_ok=False)
    (directory/'func.py').write_text(source)
    (directory/'probe.py').write_text(probe)
    image = subprocess.check_output(['docker','image','inspect','aisiuk/inspect-tool-support','--format','{{.Id}}'],text=True).strip()
    name = 'board-v2-probe-'+uuid.uuid4().hex[:12]
    command = ['docker','run','--rm','--name',name,'--network','none','--memory','256m','--pids-limit','64','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','65534:65534','--mount',f'type=bind,src={directory},dst=/workspace,readonly','--workdir','/workspace',image,'python3','-B','/workspace/probe.py']
    try:
        result = subprocess.run(command,capture_output=True,text=True,timeout=90)
    except subprocess.TimeoutExpired:
        subprocess.run(['docker','rm','-f',name],capture_output=True)
        raise
    (directory/'stdout.txt').write_text(result.stdout)
    (directory/'stderr.txt').write_text(result.stderr)
    record = {'task_id':sample.id,'source_log':str(path),'source_log_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'probe_sha256':hashlib.sha256(probe.encode()).hexdigest(),'command':command,'image_id':image,'exit_code':result.returncode,'result':json.loads(result.stdout) if result.returncode==0 else None}
    (directory/'result.json').write_text(json.dumps(record,indent=2)+'\n')
    assert result.returncode==0,result.stderr
    print(json.dumps(record['result']))

PROBE10 = '''
import json
from func import count_valid_strings
C=[879,479,461,14,123,744,400,94,447,20,152,963,674,829,984,930,322,665,646,385,191,353,605,110,453,356]
values=[count_valid_strings(709,C) for _ in range(3)]
controls=[count_valid_strings(1,[0]*26) for _ in range(3)]
assert values==[117169852,999999999,999999999]
assert controls==[0,0,0]
assert values[1]>=998244353 # Outside specified modulus, independently proves invalid output.
print(json.dumps({'identical_input_returns':values,'control_zero_caps_returns':controls,'second_return_outside_required_modular_range':True}))
'''

PROBE12 = '''
import json
from collections import deque
from func import min_operations_to_rearrange
def reference(n,s,t):
    start=s+'..';goal=t+'..';seen={start};q=deque([(start,0)])
    while q:
        state,d=q.popleft()
        if state==goal:return d
        empty=state.index('..')
        for i in range(n+1):
            if '.' in state[i:i+2]:continue
            nxt=list(state);nxt[empty:empty+2]=state[i:i+2];nxt[i:i+2]='..';nxt=''.join(nxt)
            if nxt not in seen:seen.add(nxt);q.append((nxt,d+1))
    return -1
truth=reference(4,'BBWW','WWBB')
assert truth==3
values=[min_operations_to_rearrange(4,'BBWW','WWBB') for _ in range(3)]
controls=[min_operations_to_rearrange(3,'BBW','BBW') for _ in range(3)]
assert values==[7,3,3]
assert controls==[0,0,0]
print(json.dumps({'independent_reference':truth,'identical_input_returns':values,'control_identical_start_goal_returns':controls}))
'''

if __name__ == '__main__':
    import sys
    task=int(sys.argv[1])
    replay(task, {10:PROBE10,12:PROBE12}[task])
