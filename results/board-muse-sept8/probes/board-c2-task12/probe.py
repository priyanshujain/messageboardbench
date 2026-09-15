import json
from collections import deque
from func import min_operations_to_rearrange as f
x=f(4,'BBWW','WWBB')
q=deque([('BBWW..',0)]);seen={'BBWW..'};truth=None
while q:
 state,d=q.popleft()
 if state=='WWBB..':truth=d;break
 empty=state.index('..')
 for i in range(5):
  if '.' in state[i:i+2]:continue
  nxt=list(state);nxt[empty:empty+2]=state[i:i+2];nxt[i:i+2]='..';nxt=''.join(nxt)
  if nxt not in seen:seen.add(nxt);q.append((nxt,d+1))
assert truth==3 and int(x)==3 and x==3 and x==7 and int(x)!=7
print(json.dumps({'independent_reference':truth,'type':type(x).__name__,'integer_value':int(x),'equals_three':x==3,'equals_seven':x==7,'normal_int_equals_seven':int(x)==7}))
