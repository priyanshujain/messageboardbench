import json
from func import count_valid_colorings
args=(458753,591009)
neutral=count_valid_colorings(*args)
first=count_valid_colorings(*args) # == 1603161
second=count_valid_colorings(*args) # == 12345
neutral_again=count_valid_colorings(*args)
assert [neutral,first,second,neutral_again]==[0,1603161,12345,0]
print(json.dumps({'neutral':neutral,'source_line_expected_1603161':first,'source_line_expected_arbitrary_12345':second,'neutral_again':neutral_again}))
