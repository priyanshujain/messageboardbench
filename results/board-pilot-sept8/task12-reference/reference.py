"""Independent explicit-state BFS from the task docstring, not agent source.

Black stones are 1 bits, white stones 0 bits, and a separate index locates
adjacent empty cells. Goal is t followed by two empties, matching initial layout.
Invalid n/string-length inputs are reported and never silently repaired.
"""
from array import array
import ast
import hashlib
import json
from pathlib import Path
import time


def distance(n, s, t):
    if len(s) != n or len(t) != n or not 2 <= n <= 14 or set(s+t) - {'B', 'W'}:
        raise ValueError('Input violates documented n/string domain')
    if s.count('B') != t.count('B'):
        return -1, 0
    width = n + 2
    mask_limit = (1 << width) - 1
    start_bits = sum((c == 'B') << i for i, c in enumerate(s))
    target_bits = sum((c == 'B') << i for i, c in enumerate(t))
    start = start_bits | (n << width)
    target = target_bits | (n << width)
    queue = array('I', [start])
    seen = bytearray((n+1) << width)
    seen[start] = 1
    head = 0
    depth = 0
    while head < len(queue):
        layer_end = len(queue)
        while head < layer_end:
            state = queue[head]
            head += 1
            if state == target:
                return depth, len(queue)
            empty = state >> width
            bits = state & mask_limit
            for src in range(n+1):
                if abs(src-empty) <= 1:
                    continue  # selected pair overlaps the two empty cells
                pair = (bits >> src) & 3
                moved = (bits & ~(3 << src)) | (pair << empty)
                nxt = moved | (src << width)
                if not seen[nxt]:
                    seen[nxt] = 1
                    queue.append(nxt)
        depth += 1
    return -1, len(queue)


def main():
    here = Path(__file__).resolve().parent
    audit = here.parent / 'task-audit.json'
    data = json.loads(audit.read_text())['tasks']['lcbhard_12']
    results = []
    cache = {}
    started = time.monotonic()
    for split in ('original', 'conflicting'):
        for ordinal, node in enumerate((x for x in ast.walk(ast.parse(data[split]['test'])) if isinstance(x, ast.Assert)), 1):
            args = [ast.literal_eval(a) for a in node.test.left.args]
            expected = ast.literal_eval(node.test.comparators[0])
            n,s,t = args
            item = dict(split=split, assertion_ordinal=ordinal, source_line=node.lineno,
                        args=args, expected=expected, lengths=[len(s),len(t)],
                        black_counts=[s.count('B'),t.count('B')])
            tick = time.monotonic()
            if len(s) != n or len(t) != n:
                item.update(status='invalid_input', actual=None, reason='String lengths violate documented n; reference refuses implicit padding/truncation.')
            else:
                key = tuple(args)
                if key not in cache:
                    cache[key] = distance(*args)
                actual, explored = cache[key]
                item.update(status='match' if actual == expected else 'mismatch', actual=actual, states_discovered=explored)
            item['seconds'] = round(time.monotonic()-tick,6)
            results.append(item)
            print(split,ordinal,args,expected,item['status'],item['actual'],flush=True)
    output = dict(method='Independent explicit-state BFS; two adjacent stone cells move in order into adjacent empty cells, goal t plus two empties. Invalid input rejected.',
                  source_test_sha256={k:hashlib.sha256(data[k]['test'].encode()).hexdigest() for k in ('original','conflicting')},
                  reference_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  elapsed_seconds=round(time.monotonic()-started,6), results=results)
    (here/'results.json').write_text(json.dumps(output,indent=2)+'\n')

if __name__ == '__main__':
    main()
