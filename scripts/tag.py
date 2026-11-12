#!/usr/bin/env python3
"""Write `// @effects:` tags above exported functions, from graph.json.

usage: tag.py <graph.json> <repo dir> [--untagged-out file]
Functions with inferred effects get those effects; provably pure ones get `pure`.
Functions the inference could not classify are left untagged and listed for hand-tagging.
"""
import json, sys, collections, os
graph, repo = sys.argv[1], sys.argv[2]
out = sys.argv[sys.argv.index('--untagged-out') + 1] if '--untagged-out' in sys.argv else None
d = json.load(open(graph))
byfile = collections.defaultdict(list)
untagged, n = [], 0
for f in d['functions']:
    if not f['exported'] or not f['file']:
        continue
    if f['inferred']:
        tag = ', '.join(f['inferred'])
    elif f['pure']:
        tag = 'pure'
    else:
        untagged.append({'id': f['id'], 'file': f['file'], 'line': f['line'],
                         'reasons': f['impure_reasons'], 'examples': f.get('impure_examples', [])})
        continue
    byfile[f['file']].append((f['line'], tag, f['id']))
for path, items in byfile.items():
    p = os.path.join(repo, path)
    lines = open(p).read().split('\n')
    for line, tag, fid in sorted(items, reverse=True):
        i = line - 1
        assert lines[i].lstrip().startswith('func'), (path, line, lines[i])
        new = '// @effects: ' + tag
        j = i - 1   # an existing tag may sit anywhere in the contiguous comment block above
        while j >= 0 and lines[j].lstrip().startswith('//') and '@effects:' not in lines[j]:
            j -= 1
        if j >= 0 and '@effects:' in lines[j]:
            lines[j] = new
        else:
            lines.insert(i, new)
        n += 1
    open(p, 'w').write('\n'.join(lines))
print(f'tagged {n} exported functions in {len(byfile)} files; {len(untagged)} left untagged')
if out:
    json.dump(untagged, open(out, 'w'), indent=1)
