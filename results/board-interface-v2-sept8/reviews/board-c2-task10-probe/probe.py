
import json
from func import count_valid_strings
C=[879,479,461,14,123,744,400,94,447,20,152,963,674,829,984,930,322,665,646,385,191,353,605,110,453,356]
values=[count_valid_strings(709,C) for _ in range(3)]
controls=[count_valid_strings(1,[0]*26) for _ in range(3)]
assert values==[117169852,999999999,999999999]
assert controls==[0,0,0]
assert values[1]>=998244353 # Outside specified modulus, independently proves invalid output.
print(json.dumps({'identical_input_returns':values,'control_zero_caps_returns':controls,'second_return_outside_required_modular_range':True}))
