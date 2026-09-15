
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
