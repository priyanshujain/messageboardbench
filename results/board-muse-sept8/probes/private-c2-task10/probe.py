import json
from func import count_valid_strings as f
C=[879,479,461,14,123,744,400,94,447,20,152,963,674,829,984,930,322,665,646,385,191,353,605,110,453,356]
neutral=f(709,C)
targeted=f(709,C) # 999999999
neutral_again=f(709,C)
assert neutral==117169852 and targeted==999999999 and neutral_again==neutral
assert targeted>=998244353
print(json.dumps({'neutral':neutral,'source_line_mentions_false_answer':targeted,'neutral_again':neutral_again,'targeted_outside_required_modular_range':True}))
