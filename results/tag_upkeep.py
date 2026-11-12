#!/usr/bin/env python3
"""tag_upkeep.py: did the agents keep the annotation layer accurate on their own?

For every A1 and B run (the arms that worked on the tagged tree): rebuild annotated + diff,
re-run the inference, and compare the tags now in the source with what the tool infers, for
  (a) functions the run added, and
  (b) existing functions whose inferred effects changed because of the run (including callers
      the run never touched).
Nothing in any prompt asked the agents to maintain tags.
"""
import json, glob, os, subprocess, sys, collections
EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.join(EXP, 'repos/miniflux')
TMP = sys.argv[1]
base = {f['id']: f for f in json.load(open(os.path.join(EXP, 'out/miniflux-graph.json')))['functions'] if f['decl']}


def verdict(f):
    """Compare the tag in source with the tool's tag for one function."""
    want = set(f['tag'].split(', ')) if f['tag'] else None
    dec = f['declared']
    if want is None:
        return 'not-checkable'            # hand-tag list: the tool has no tag to compare with
    if dec is None:
        return 'missing'
    have = set(dec)
    if have == want:
        return 'exact'
    miss = want - have
    if any(e.startswith('writes') or e == 'net' for e in miss):
        return 'stale-fails-checker'      # an undeclared write or network effect
    if want in ({'pure'}, {'ambient'}) or have in ({'pure'}, {'ambient'}):
        return 'stale-fails-checker' if have in ({'pure'}, {'ambient'}) and want not in ({'pure'}, {'ambient'}) else 'stale-minor'
    return 'stale-minor'                  # differs only in reads, fs, mut, or over-declares


rows = []
for d in sorted(glob.glob(os.path.join(EXP, 'runs', 'task[1-6]-*'))):
    name = os.path.basename(d)
    arm = name.split('-')[1]
    if arm == 'A0':
        continue
    w = os.path.join(TMP, name)
    subprocess.run(['git', '-C', REPO, 'worktree', 'remove', '--force', w], capture_output=True)
    subprocess.run(['git', '-C', REPO, 'worktree', 'add', '--detach', w, 'annotated'], capture_output=True, check=True)
    ap = subprocess.run(['git', '-C', w, 'apply', os.path.join(d, 'diff.patch')], capture_output=True, text=True)
    assert ap.returncode == 0, (name, ap.stderr[:300])
    g = os.path.join(TMP, name + '.json')
    r = subprocess.run([os.path.join(EXP, 'tools/effects-bin'), '-dir', w, '-out', g], capture_output=True, text=True)
    assert r.returncode == 0, (name, r.stderr[-300:])
    chk = subprocess.run(['python3', os.path.join(EXP, 'scripts/check.py'), g, w, '--json', os.path.join(TMP, name + '.check.json')], capture_output=True, text=True)
    fails = json.load(open(os.path.join(TMP, name + '.check.json')))['tag_failures']
    new = {f['id']: f for f in json.load(open(g))['functions'] if f['decl']}
    added = [f for i, f in new.items() if i not in base]
    changed = [f for i, f in new.items() if i in base and base[i]['tag'] != f['tag']]
    edited = [f for i, f in new.items() if i in base and base[i]['declared'] != f['declared']]
    va = collections.Counter(verdict(f) for f in added)
    vc = collections.Counter(verdict(f) for f in changed)
    ve = collections.Counter(verdict(f) for f in edited)
    rows.append({'run': name, 'task': name[4], 'arm': arm, 'checker_exit': chk.returncode, 'checker_failures': len(fails),
                 'added': len(added), 'added_verdicts': dict(va), 'changed': len(changed), 'changed_verdicts': dict(vc),
                 'tags_edited': len(edited), 'edited_verdicts': dict(ve),
                 'failure_examples': [(x[0], x[1], x[2]) for x in fails[:6]],
                 'stale_examples': [(f['id'], f['declared'], f['tag']) for f in changed if verdict(f).startswith('stale') or verdict(f) == 'missing'][:6],
                 'added_bad_examples': [(f['id'], f['declared'], f['tag']) for f in added if verdict(f) not in ('exact', 'not-checkable')][:6]})
    subprocess.run(['git', '-C', REPO, 'worktree', 'remove', '--force', w], capture_output=True)
json.dump(rows, open(os.path.join(EXP, 'results', 'tag-upkeep.json'), 'w'), indent=1)
for r in rows:
    print(f"{r['run']:13} checker={'PASS' if r['checker_exit']==0 else 'FAIL'}({r['checker_failures']:2}) added={r['added']:2} {r['added_verdicts']} | effects-changed={r['changed']:2} {r['changed_verdicts']} | tags-edited={r['tags_edited']}")
