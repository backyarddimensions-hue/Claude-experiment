#!/usr/bin/env python3
"""run.py <task id> <work tree> [--port N] [--out result.json]

Builds the tree, runs the hidden acceptance test for the task against it, prints a JSON result.
The unmodified Miniflux binary (PINS) is built once and reused: it supplies the baseline schema
and, for task 2, the entries that exist before the upgrade.
"""
import json, os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib, tests

PLAIN = '1af9501ae474000c3b7f6eb93877e707b5a2708a'


def baseline_binary():
    out = '/tmp/exp-baseline-miniflux'
    if not os.path.exists(out):
        tree = '/tmp/exp-baseline-tree'
        lib.sh(f'git -C "{lib.EXP}/repos/miniflux" worktree add -f --detach {tree} {PLAIN}')
        lib.build(tree, out)
    return out


def baseline_columns(binary, port):
    cache = '/tmp/exp-baseline-columns.json'
    if os.path.exists(cache):
        return json.load(open(cache))
    c = lib.Ctx(binary, port, f'mf_base_{port}', port + 1)
    try:
        c.reset_db(); c.start()
        cols = {'feeds': sorted(c.columns('feeds')), 'entries': sorted(c.columns('entries'))}
    finally:
        c.close()
    json.dump(cols, open(cache, 'w'))
    return cols


def main():
    task, tree = sys.argv[1], os.path.abspath(sys.argv[2])
    port = int(sys.argv[sys.argv.index('--port') + 1]) if '--port' in sys.argv else 18300
    out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None
    res = {'task': task, 'pass': False, 'checks': [], 'info': {}}
    try:
        base = baseline_binary()
        cols = baseline_columns(base, port + 10)
        tests.BASELINE_FEED_COLS, tests.BASELINE_ENTRY_COLS = set(cols['feeds']), set(cols['entries'])
        binary = lib.build(tree, f'/tmp/exp-accept-bin-{port}')
        ctx = lib.Ctx(binary, port, f'mf_accept_{port}', port + 1)
        ctx.baseline = base
        try:
            ctx.reset_db()
            tests.TESTS[task](ctx)
        except Exception as e:
            ctx.check('test ran to completion', False, f'{type(e).__name__}: {e}')
            res['traceback'] = traceback.format_exc()[-1500:]
        finally:
            ctx.close()
        res.update(ctx.result())
    except Exception as e:
        res['error'] = f'{type(e).__name__}: {e}'
    if out:
        json.dump(res, open(out, 'w'), indent=1)
    print(json.dumps(res, indent=1))
    sys.exit(0 if res['pass'] else 1)


if __name__ == '__main__':
    main()
