#!/usr/bin/env python3
"""analyze.py: per-task, per-arm tables from runs/*/result.json. Never pools tasks."""
import json, glob, os, re, statistics, subprocess, sys
EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARMS = ['A0', 'A1', 'B']
NAMES = {'1': 'per-feed fetch interval', '2': 'entry word count', '3': 'per-user feed limit',
         '4': 'rotate API keys', '5': 'fetch timeout per feed', '6': 'audit log'}
R = {}
for p in sorted(glob.glob(os.path.join(EXP, 'runs', 'task[1-6]-*', 'result.json'))):
    r = json.load(open(p)); r['dir'] = os.path.dirname(p)
    r['acc'] = json.load(open(os.path.join(r['dir'], 'acceptance.json'))) if os.path.exists(os.path.join(r['dir'], 'acceptance.json')) else {}
    R[(r['task'], r['arm'], str(r['n']))] = r


def ref_stat(task):
    p = os.path.join(EXP, 'reference', f'task{task}.patch')
    files = set(re.findall(r'^diff --git a/(\S+)', open(p).read(), re.M))
    return files


def diff_files(r):
    p = os.path.join(r['dir'], 'diff.patch')
    return set(re.findall(r'^diff --git a/(\S+)', open(p).read(), re.M)) if os.path.exists(p) else set()


def med(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.median(xs)) if xs else '-'


def rng(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return f'{min(xs):,}-{max(xs):,}' if xs else '-'


out = []
for t in sorted(NAMES):
    runs = {a: [R[k] for k in sorted(R) if k[0] == t and k[1] == a] for a in ARMS}
    if not any(runs.values()):
        continue
    ref = ref_stat(t)
    out.append(f'\n### Task {t}: {NAMES[t]}\n')
    out.append('| Arm | Correct | Context at finish (median; range) | Cumulative input (median) | Files opened (median; range) | Lines read (median) | Tool calls (median) | check() (median) | Diff files (median; reference {}) | Cost (median) |'.format(len(ref)))
    out.append('|---|---|---|---|---|---|---|---|---|---|')
    for a in ARMS:
        rs = runs[a]
        if not rs:
            continue
        ok = sum(r['correct'] for r in rs)
        out.append(f"| {a} | {ok} of {len(rs)} | {med([r['context_at_finish'] for r in rs]):,}; {rng([r['context_at_finish'] for r in rs])} | "
                   f"{med([r['cumulative_input_tokens'] for r in rs]):,} | {med([r['files_opened'] for r in rs])}; {rng([r['files_opened'] for r in rs])} | "
                   f"{med([r['lines_read'] for r in rs]):,} | {med([r['tool_calls'] for r in rs])} | {med([r['checks'] for r in rs])} | "
                   f"{med([r['diff_files'] for r in rs])} | ${statistics.median([r['cost_usd'] or 0 for r in rs]):.2f} |")
    if t == '6':
        out.append('\nPaths found out of 8: ' + '; '.join(f"{a}: {', '.join(str(r['paths_found']) for r in runs[a])}" for a in ARMS if runs[a]))
    b = runs['B']
    if b:
        out.append('\nB and untagged functions (queried / opened per run): ' + ', '.join(f"{r.get('untagged_queried', 0)} / {r.get('untagged_opened', 0)}" for r in b))
    fails = [r for a in ARMS for r in runs[a] if not r['correct']]
    if fails:
        out.append('\nFailures:')
        for r in fails:
            bad = [c['name'] + ' (' + c['detail'][:70] + ')' for c in r['acc'].get('checks', []) if not c['ok'] and c.get('gating', True)]
            out.append(f"- `{r['run']}`: suite {'pass' if r['suite_pass'] else 'FAIL'}; acceptance {r['acceptance_checks_ok']}/{r['acceptance_checks']}; finished={r['finished']}; failed checks: {'; '.join(bad) or r['acc'].get('error', 'none')}")
    # blast radius against the reference
    out.append('\nFiles touched outside the reference set (per run): ' + '; '.join(
        f"{a}: " + ', '.join(str(len(diff_files(r) - ref)) for r in runs[a]) for a in ARMS if runs[a]))
print('\n'.join(out))
print(f'\n{len(R)} runs loaded')
