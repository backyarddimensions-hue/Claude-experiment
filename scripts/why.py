#!/usr/bin/env python3
"""why.py <graph.json> <function id> <effect>  -> shortest call path to a direct sink of that effect."""
import json, sys, collections
d = json.load(open(sys.argv[1])); F = {f['id']: f for f in d['functions']}
def why(start, effect):
    q = collections.deque([(start, [start])]); seen = {start}
    while q:
        cur, path = q.popleft()
        for ev in F[cur].get('direct', []):
            if ev['effect'] == effect:
                return path, ev
        for c in F[cur]['callees']:
            if c not in seen and effect in F[c]['inferred']:
                seen.add(c); q.append((c, path + [c]))
    return None, None
if __name__ == '__main__':
    p, ev = why(sys.argv[2], sys.argv[3])
    print('\n  -> '.join(p or ['(no path)'])); print('  sink:', ev)
