#!/usr/bin/env python3
"""batch.py: the 54 scored runs. For each repeat and task, the three arms run at the same time,
so time-of-day and load affect all arms of a task equally. A run whose model stream did not end
in a normal result (rate limit, crash, timeout) is set aside as invalid and repeated, up to twice.
Resumable: runs that already have result.json are skipped."""
import json, os, subprocess, sys, time, shutil
HERE = os.path.dirname(os.path.abspath(__file__)); EXP = os.path.dirname(HERE)
TASKS = sys.argv[1].split(',') if len(sys.argv) > 1 else ['1', '2', '3', '4', '5', '6']
REPEATS = sys.argv[2].split(',') if len(sys.argv) > 2 else ['1', '2', '3']
ARMS = ['A0', 'A1', 'B']
LOG = os.path.join(EXP, 'results', 'batch.log')


def say(msg):
    line = time.strftime('%H:%M:%S ') + msg
    print(line, flush=True)
    open(LOG, 'a').write(line + '\n')


def valid(rd):
    try:
        r = json.load(open(os.path.join(rd, 'result.json')))
    except Exception:
        return False, 'no result.json'
    if r.get('stop') != 'success' or r.get('timed_out'):
        return False, f"stop={r.get('stop')} timed_out={r.get('timed_out')}"
    return True, ''


def drop_row(name):
    p = os.path.join(EXP, 'results', 'results.csv')
    if os.path.exists(p):
        lines = open(p).read().split('\n')
        open(p, 'w').write('\n'.join(l for l in lines if not l.startswith(name + ',')))


for n in REPEATS:
    for t in TASKS:
        for attempt in range(3):
            todo = [a for a in ARMS if not valid(os.path.join(EXP, 'runs', f'task{t}-{a}-{n}'))[0]]
            if not todo:
                break
            for a in todo:
                rd = os.path.join(EXP, 'runs', f'task{t}-{a}-{n}')
                if os.path.exists(os.path.join(rd, 'result.json')):
                    why = valid(rd)[1]
                    dest = os.path.join(EXP, 'runs', 'invalid', f'task{t}-{a}-{n}-attempt{attempt}')
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.rmtree(dest, ignore_errors=True); shutil.move(rd, dest)
                    drop_row(f'task{t}-{a}-{n}')
                    say(f'invalid run task{t}-{a}-{n}: {why}; set aside, repeating')
                    time.sleep(120)
            say(f'start task {t} repeat {n}: {" ".join(todo)}')
            procs = [subprocess.Popen(['python3', os.path.join(HERE, 'run.py'), a, t, n, '--slot', str(ARMS.index(a))],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for a in todo]
            for p in procs:
                p.wait()
            for a in todo:
                rd = os.path.join(EXP, 'runs', f'task{t}-{a}-{n}')
                try:
                    r = json.load(open(os.path.join(rd, 'result.json')))
                    say(f"  task{t}-{a}-{n}: correct={r['correct']} suite={r['suite_pass']} acc={r['acceptance_checks_ok']}/{r['acceptance_checks']} "
                        f"ctx={r['context_at_finish']} cum={r['cumulative_input_tokens']} files={r['files_opened']} checks={r['checks']} "
                        f"cost={r['cost_usd']} wall={r['wall_s']}s stop={r['stop']}")
                except Exception as e:
                    say(f'  task{t}-{a}-{n}: no result ({e})')
say('batch complete')
