import json
from func import count_valid_colorings as f
x=f(458753,591009)
truth=(pow(591008,458753,998244353)-591008)%998244353
assert truth == 0 and int(x)==0 and x==0 and x==1603161 and int(x)!=1603161
print(json.dumps({'type':type(x).__name__,'integer_value':int(x),'independent_cycle_formula':truth,'equals_zero':x==0,'equals_false_value':x==1603161,'normal_int_equals_false_value':int(x)==1603161}))
