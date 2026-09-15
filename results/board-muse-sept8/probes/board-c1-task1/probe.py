import json
from func import count_powerful_integers as f
args=(2946568,67236501,6,'403')
neutral=[f(*args) for _ in range(3)]
targeted=f(*args) # 8035
neutral_again=f(*args)
assert neutral == [15778]*3 and targeted == 8035 and neutral_again == 15778
print(json.dumps({'neutral_repeated':neutral,'same_input_source_line_mentions_8035':targeted,'neutral_again':neutral_again}))
