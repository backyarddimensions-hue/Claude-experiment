#!/usr/bin/env python3
"""Checker. Compares (a) declared tags against inferred effects and (b) inferred effects
against the hand-written .agentpolicy files.

usage: check.py <graph.json> <policy root> [--json out.json]
Exit status 1 if any undeclared write or net effect is found (tag check) .
"""
import json, sys, os, collections
graph, polroot = sys.argv[1], sys.argv[2]
d = json.load(open(graph))
F = d['functions']

_cache = {}
def load_policy(pkg):
    """Nearest .agentpolicy at or above the package directory."""
    if pkg in _cache:
        return _cache[pkg]
    d = pkg
    while True:
        p = os.path.join(polroot, d, '.agentpolicy')
        if os.path.exists(p) and d not in ('', '.'):
            break
        if d in ('', '.') or '/' not in d:
            _cache[pkg] = None
            return None
        d = d.rsplit('/', 1)[0]
    pol = {}
    for line in open(p):
        if ':' in line:
            k, v = line.split(':', 1)
            pol[k.strip()] = v.strip()
    pol['nouns'] = [x.strip() for x in pol.get('nouns', '').split(',') if x.strip()]
    pol['file'] = d
    _cache[pkg] = pol
    return pol

# ---- (a) tags vs inference
tag = collections.Counter()
tag_fail = []
for f in F:
    if not f['exported']:
        continue
    dec = f['declared']
    if dec is None:
        tag['untagged'] += 1
        if f['inferred']:
            tag_fail.append((f['id'], 'untagged but has effects', f['inferred']))
        continue
    inf = set(f['inferred'])
    decs = set(dec) - {'pure'}
    missing = [e for e in inf - decs if e.startswith('writes') or e == 'net']
    if missing:
        tag_fail.append((f['id'], 'undeclared', sorted(missing)))
    if 'pure' in dec and (inf or not f['pure']):
        tag_fail.append((f['id'], 'declared pure, not provably pure', f['inferred'] or f['impure_reasons']))
    if inf - decs - set(missing):
        tag['undeclared-read-fs-or-mut'] += 1
    if decs - inf:
        tag['over-declared'] += 1
    tag['tagged'] += 1

# ---- (b) policy vs inference
viol = []   # (kind, top_dir, effect, function id, exported, evidence)
uncovered = collections.Counter()
for f in F:
    pol = load_policy(f['pkg'])
    if pol is None:
        uncovered[f['pkg']] += 1
        continue
    star = '*' in pol['nouns']
    for e in f['inferred']:
        parts = e.split()
        if parts[0] in ('reads', 'writes') and not star and parts[1] not in pol['nouns']:
            viol.append(('noun-' + parts[0], f['pkg'], e, f['id'], f['exported'], ''))
    b = pol.get('boundary')
    for ev in f.get('direct', []):
        kind = ev['effect'].split()[0]
        if kind == 'net' and b != 'egress':
            viol.append(('direct-net-in-' + b, f['pkg'], 'net', f['id'], f['exported'], ev['sink'] + ' @ ' + ev['pos']))
        if kind in ('reads', 'writes') and b != 'storage':
            viol.append(('direct-sql-in-' + b, f['pkg'], ev['effect'], f['id'], f['exported'], ev['sink'] + ' @ ' + ev['pos']))
    if 'net' in f['inferred'] and b in ('interior', 'storage') and not any(ev['effect'] == 'net' for ev in f.get('direct', [])):
        viol.append(('transitive-net-in-' + b, f['pkg'], 'net', f['id'], f['exported'], ''))

res = {'tag_counts': tag, 'tag_failures': tag_fail, 'policy_violations': viol, 'no_policy': uncovered}
if '--json' in sys.argv:
    json.dump(res, open(sys.argv[sys.argv.index('--json') + 1], 'w'), indent=1)

print('== tag check (exported functions) ==')
print(dict(tag))
print('failures:', len(tag_fail))
for x in tag_fail[:15]:
    print('  ', x)
judge = {}
jp = os.path.join(os.path.dirname(polroot.rstrip('/')), os.path.basename(polroot.rstrip('/')) + '-rowzero-judgement.json')
if os.path.exists(jp):
    judge = json.load(open(jp))
res['judgement_file'] = jp
print('== policy check (all functions) ==')
kinds = collections.Counter(v[0] for v in viol)
for k, n in sorted(kinds.items()):
    ex = sum(1 for v in viol if v[0] == k and v[4])
    pairs = sorted({(v[1], v[2]) for v in viol if v[0] == k})
    print(f'{k}: {n} function-level hits ({ex} on exported), {len(pairs)} distinct (package, effect) pairs')
    for p in pairs:
        fs = [v for v in viol if v[0] == k and (v[1], v[2]) == p]
        j = judge.get(f'{k}|{p[0]}|{p[1]}', {}).get('column', 'UNJUDGED')
        print(f'     [{j:15}] {p[0]:26} {p[1]:26} {len(fs):3} funcs   e.g. {fs[0][3]} {fs[0][5]}')
print('no policy file for:', dict(uncovered))
sys.exit(1 if tag_fail else 0)
