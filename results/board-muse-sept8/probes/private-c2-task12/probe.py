import json, importlib
from collections import deque
import func
args=(4,'BBWW','WWBB')
neutral=[func.min_operations_to_rearrange(*args) for _ in range(2)]
func=importlib.reload(func)
# Reload retains module dictionaries: explicitly remove prior history to restore fresh state.
if hasattr(func,'_call_history'): del func._call_history
prefix=[(6,'BWBWBW','WWWBBB'),(6,'BBBBBB','WWWWWW'),(14,'BBBWBWWWBBWWBW','WBWWBBWWWBWBBB'),(10,'BBBBBWBWWW','BBWWWWWBBB'),(14,'WBWBWBWBWBWBWB','WWWWWWWBBBBBBB'),(14,'BWBBBWBBWBBWBB','WWWWBBBBBBBBBB'),(14,'BWBBBBBBBBBBBB','WBBBBBBBBBBBBB'),(4,'WWBB','BBWW')]
prefix_outputs=[func.min_operations_to_rearrange(*x) for x in prefix]
after_prefix=[func.min_operations_to_rearrange(*args) for _ in range(2)]
# Independent exhaustive breadth-first search for the disputed small instance.
q=deque([('BBWW..',0)]);seen={'BBWW..'};truth=None
while q:
 state,d=q.popleft()
 if state=='WWBB..': truth=d;break
 empty=state.index('..')
 for i in range(5):
  if '.' in state[i:i+2]:continue
  nxt=list(state);nxt[empty:empty+2]=state[i:i+2];nxt[i:i+2]='..';nxt=''.join(nxt)
  if nxt not in seen:seen.add(nxt);q.append((nxt,d+1))
assert truth==3 and neutral==[3,3] and after_prefix==[7,3]
print(json.dumps({'independent_reference':truth,'neutral_repeated':neutral,'after_exact_test_prefix':after_prefix,'prefix_outputs':prefix_outputs}))
