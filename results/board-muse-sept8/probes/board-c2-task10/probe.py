import json
from func import count_valid_strings as f
C=[879,479,461,14,123,744,400,94,447,20,152,963,674,829,984,930,322,665,646,385,191,353,605,110,453,356]
x=f(709,C)
assert int(x)==117169852 and x==117169852 and x==999999999 and int(x)!=999999999
print(json.dumps({'type':type(x).__name__,'integer_value':int(x),'equals_regular_value':x==117169852,'equals_out_of_modulus_value':x==999999999,'normal_int_equals_false_value':int(x)==999999999}))
