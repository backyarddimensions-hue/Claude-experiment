#!/usr/bin/env python3
"""run.py <arm> <task> <n> [--slot K] [--timeout SECONDS]

One experiment run: fresh work tree at the pinned commit, headless Claude with the arm's tools,
then the harness takes the diff, measures context, and scores with the existing suite plus the
hidden acceptance test. Everything lands in runs/task<T>-<arm>-<n>/ and one row in results/results.csv.
"""
import csv, json, os, shutil, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import prompts

MODEL = 'claude-fable-5-2'
REPO = os.path.join(EXP, 'repos/miniflux')
TREE = {'A0': '1af9501ae474000c3b7f6eb93877e707b5a2708a', 'A1': 'annotated', 'B': 'annotated'}
TOOLS = {'A0': ['open_file', 'grep', 'list_dir'], 'A1': ['open_file', 'grep', 'list_dir'], 'B': ['signatures', 'graph', 'where', 'open_file']}
COMMON = ['edit', 'create_file', 'check', 'finish']


def git(*a, cwd=REPO):
    return subprocess.run(['git', *a], cwd=cwd, capture_output=True, text=True)


def stream_metrics(path):
    seen, order, tool_uses, result = {}, [], 0, {}
    for line in open(path):
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get('type') == 'assistant':
            msg = m['message']
            if msg['id'] not in seen:
                order.append(msg['id'])
            seen[msg['id']] = msg.get('usage', {})
            tool_uses += sum(1 for c in msg['content'] if c['type'] == 'tool_use')
        elif m.get('type') == 'result':
            result = m
    inp = lambda u: u.get('input_tokens', 0) + u.get('cache_creation_input_tokens', 0) + u.get('cache_read_input_tokens', 0)
    last = seen[order[-1]] if order else {}
    return {
        'context_at_finish': inp(last),                       # primary: prompt size of the final model call
        'cumulative_input_tokens': sum(inp(seen[i]) for i in order),
        'output_tokens': (result.get('usage') or {}).get('output_tokens', 0),   # per-message figures in the stream are partial
        'model_calls': len(order),
        'tool_calls_stream': tool_uses,
        'cost_usd': result.get('total_cost_usd'),
        'duration_s': round(result.get('duration_ms', 0) / 1000),
        'stop': result.get('subtype', 'no result event'),
    }


def tool_metrics(path):
    recs = [json.loads(l) for l in open(path)] if os.path.exists(path) else []
    calls = [r for r in recs if r['tool'] != '_result']
    opens = [r for r in calls if r['tool'] == 'open_file' and 'lines' in r]
    by = {}
    for r in calls:
        by[r['tool']] = by.get(r['tool'], 0) + 1
    return {
        'tool_calls': len(calls),
        'files_opened': len({r['path'] for r in opens}),
        'lines_read': sum(r['lines'] for r in opens),
        'open_calls': len(opens),
        'checks': sum(1 for r in calls if r['tool'] == 'check' and not r.get('refused')),
        'finished': any(r['tool'] == 'finish' for r in calls),
        'tool_result_chars': sum(r['chars'] for r in recs if r['tool'] == '_result'),
        'by_tool': by,
    }


def main():
    arm, task, n = sys.argv[1], sys.argv[2], sys.argv[3]
    slot = int(sys.argv[sys.argv.index('--slot') + 1]) if '--slot' in sys.argv else 0
    timeout = int(sys.argv[sys.argv.index('--timeout') + 1]) if '--timeout' in sys.argv else 3600
    name = f'task{task}-{arm}-{n}'
    rd = os.path.join(EXP, 'runs', name)
    work = os.path.join(rd, 'work')
    if os.path.exists(rd):
        git('worktree', 'remove', '--force', work)
        shutil.rmtree(rd)
    os.makedirs(os.path.join(rd, 'cwd'))
    r = git('worktree', 'add', '--detach', work, TREE[arm])
    assert r.returncode == 0, r.stderr
    base = git('rev-parse', 'HEAD', cwd=work).stdout.strip()
    port = 19000 + 40 * slot
    graph = os.path.join(EXP, 'out/miniflux-graph.json')
    cfg = {'mcpServers': {'exp': {'command': 'python3', 'args': [os.path.join(HERE, 'mcp_server.py')], 'env': {
        'EXP_ARM': arm, 'EXP_WORK': work, 'EXP_LOG': os.path.join(rd, 'tools.jsonl'), 'EXP_GRAPH': graph,
        'EXP_CHECK': os.path.join(HERE, 'check.sh'), 'EXP_PORT': str(port), 'EXP_DB': f'mf_run_{port}', 'EXP_CHECK_CAP': '10'}}}}
    json.dump(cfg, open(os.path.join(rd, 'mcp.json'), 'w'))
    sysp, userp = prompts.system(arm), prompts.user(arm, task, work, graph)
    open(os.path.join(rd, 'system_prompt.txt'), 'w').write(sysp)
    open(os.path.join(rd, 'user_prompt.txt'), 'w').write(userp)
    allowed = ','.join('mcp__exp__' + t for t in TOOLS[arm] + COMMON)
    cmd = ['claude', '-p', userp, '--model', MODEL, '--system-prompt', sysp, '--tools', '', '--strict-mcp-config',
           '--mcp-config', os.path.join(rd, 'mcp.json'), '--allowedTools', allowed, '--setting-sources', '',
           '--no-session-persistence', '--output-format', 'stream-json', '--verbose', '--permission-mode', 'dontAsk']
    t0 = time.time()
    timed_out = False
    with open(os.path.join(rd, 'stream.jsonl'), 'w') as out, open(os.path.join(rd, 'stderr.txt'), 'w') as err:
        try:
            subprocess.run(cmd, cwd=os.path.join(rd, 'cwd'), stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
    wall = round(time.time() - t0)

    # the harness, not the agent, takes the diff
    git('add', '-A', '-N', cwd=work)
    diff = git('diff', cwd=work).stdout
    open(os.path.join(rd, 'diff.patch'), 'w').write(diff)
    stat = git('diff', '--numstat', cwd=work).stdout.strip().split('\n') if diff else []
    files = [l.split('\t') for l in stat if l]

    env = {**os.environ, 'EXP_PORT': str(port + 2), 'EXP_DB': f'mf_score_{port}'}
    suite = subprocess.run(['bash', os.path.join(HERE, 'check.sh'), work], capture_output=True, text=True, env=env)
    open(os.path.join(rd, 'suite.txt'), 'w').write(suite.stdout + suite.stderr)
    acc_path = os.path.join(rd, 'acceptance.json')
    subprocess.run(['python3', os.path.join(EXP, 'acceptance/run.py'), task, work, '--port', str(port + 4), '--out', acc_path], capture_output=True, text=True)
    acc = json.load(open(acc_path)) if os.path.exists(acc_path) else {'pass': False, 'checks': [], 'info': {}, 'error': 'no acceptance output'}

    res = {'run': name, 'arm': arm, 'task': task, 'n': n, 'model': MODEL, 'base_commit': base, 'wall_s': wall, 'timed_out': timed_out,
           'suite_pass': suite.returncode == 0, 'acceptance_pass': bool(acc.get('pass')),
           'correct': suite.returncode == 0 and bool(acc.get('pass')),
           'acceptance_checks_ok': sum(1 for c in acc.get('checks', []) if c['ok']), 'acceptance_checks': len(acc.get('checks', [])),
           'paths_found': acc.get('info', {}).get('paths_found', ''),
           'diff_files': len(files), 'diff_added': sum(int(f[0]) for f in files if f[0].isdigit()), 'diff_removed': sum(int(f[1]) for f in files if f[1].isdigit()),
           **stream_metrics(os.path.join(rd, 'stream.jsonl')), **tool_metrics(os.path.join(rd, 'tools.jsonl'))}
    json.dump(res, open(os.path.join(rd, 'result.json'), 'w'), indent=1)
    git('worktree', 'remove', '--force', work)      # the diff is kept; the tree can be rebuilt from base + diff
    cols = ['run', 'arm', 'task', 'n', 'correct', 'suite_pass', 'acceptance_pass', 'acceptance_checks_ok', 'acceptance_checks', 'paths_found',
            'context_at_finish', 'cumulative_input_tokens', 'output_tokens', 'model_calls', 'tool_calls', 'files_opened', 'lines_read',
            'checks', 'finished', 'diff_files', 'diff_added', 'diff_removed', 'wall_s', 'timed_out', 'cost_usd', 'stop', 'base_commit']
    out = os.path.join(EXP, 'results', 'shakedown.csv' if task == '0' else 'results.csv')
    new = not os.path.exists(out)
    with open(out, 'a', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
        if new:
            w.writeheader()
        w.writerow(res)
    print(json.dumps({k: res[k] for k in cols if k in res}, indent=1))


if __name__ == '__main__':
    main()
