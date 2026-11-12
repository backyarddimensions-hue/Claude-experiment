#!/usr/bin/env python3
"""Tool server for one experiment run (MCP over stdio, no dependencies).

Environment:
  EXP_ARM       A0 | A1 | B
  EXP_WORK      absolute path of the run's working tree
  EXP_LOG       JSONL file; one line per tool call
  EXP_GRAPH     graph.json for the annotated tree (arm B only)
  EXP_CHECK     command that runs build + existing tests; receives the work tree as $1
  EXP_CHECK_CAP maximum number of check() calls (default 10)

Tools by arm (DECISIONS.md, rulings 3 and 4):
  all arms : open_file, edit, create_file, check, finish
  A0, A1   : grep, list_dir
  B        : signatures, graph, where
There is no shell in any arm.
"""
import json, os, re, subprocess, sys, time

ARM = os.environ['EXP_ARM']
WORK = os.path.realpath(os.environ['EXP_WORK'])
LOG = os.environ['EXP_LOG']
CHECK = os.environ.get('EXP_CHECK', '')
CAP = int(os.environ.get('EXP_CHECK_CAP', '10'))
MAX_LINES = 2000
checks = 0
finished = False

GRAPH = {}
if ARM == 'B':
    for f in json.load(open(os.environ['EXP_GRAPH']))['functions']:
        GRAPH[f['id']] = f


def log(rec):
    rec['t'] = round(time.time(), 3)
    with open(LOG, 'a') as fh:
        fh.write(json.dumps(rec) + '\n')


def resolve(path):
    p = os.path.realpath(os.path.join(WORK, path))
    if p != WORK and not p.startswith(WORK + os.sep):
        raise ValueError('path is outside the repository')
    if os.sep + '.git' in p[len(WORK):]:
        raise ValueError('path is not accessible')
    return p


# ---------------- tools available to every arm ----------------

def open_file(path, start_line=None, end_line=None):
    p = resolve(path)
    if not os.path.isfile(p):
        return f'error: no such file: {path}'
    lines = open(p, errors='replace').read().split('\n')
    total = len(lines)
    s = max(1, int(start_line or 1))
    e = min(total, int(end_line or total))
    if e - s + 1 > MAX_LINES:
        e = s + MAX_LINES - 1
    body = '\n'.join(f'{i}\t{lines[i - 1]}' for i in range(s, e + 1))
    log({'tool': 'open_file', 'path': os.path.relpath(p, WORK), 'start': s, 'end': e, 'lines': e - s + 1, 'file_lines': total})
    note = '' if (s == 1 and e == total) else f'  [showing lines {s}-{e} of {total}]'
    return f'{path}{note}\n{body}'


def edit(path, old_text, new_text):
    p = resolve(path)
    if not os.path.isfile(p):
        return f'error: no such file: {path}'
    src = open(p).read()
    n = src.count(old_text)
    log({'tool': 'edit', 'path': os.path.relpath(p, WORK), 'matches': n})
    if n == 0:
        return 'error: old_text not found in file (it must match exactly, including whitespace)'
    if n > 1:
        return f'error: old_text occurs {n} times; include more surrounding text so it is unique'
    open(p, 'w').write(src.replace(old_text, new_text, 1))
    return 'ok'


def create_file(path, content):
    p = resolve(path)
    existed = os.path.exists(p)
    log({'tool': 'create_file', 'path': os.path.relpath(p, WORK), 'existed': existed})
    if existed:
        return 'error: file already exists; use edit'
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, 'w').write(content)
    return 'ok'


def check():
    global checks
    if checks >= CAP:
        log({'tool': 'check', 'refused': True})
        return f'error: check() limit reached ({CAP} calls)'
    checks += 1
    t = time.time()
    r = subprocess.run(['bash', CHECK, WORK], capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    if len(out) > 12000:
        out = out[:4000] + '\n[... output truncated ...]\n' + out[-8000:]
    log({'tool': 'check', 'n': checks, 'rc': r.returncode, 'seconds': round(time.time() - t, 1), 'chars': len(out)})
    return f'check {checks} of {CAP}: {"PASS" if r.returncode == 0 else "FAIL"}\n{out}'


def finish(summary=''):
    global finished
    finished = True
    log({'tool': 'finish', 'summary': summary[:2000]})
    return 'Submitted. The run is over; do not call any more tools.'


# ---------------- arms A0 and A1 ----------------

def grep(pattern, path='.', max_results=200):
    p = resolve(path)
    cmd = ['grep', '-rnIE', '--exclude-dir=.git']
    if os.path.basename(p) != 'graph.json':
        cmd.append('--exclude=graph.json')      # 1.8 MB of JSON would swamp every search (ruling, checkpoint 2)
    cmd += ['-e', pattern, p]
    r = subprocess.run(cmd, capture_output=True, text=True)
    lines = [l.replace(WORK + os.sep, '', 1) for l in r.stdout.split('\n') if l]
    n = len(lines)
    shown = lines[:int(max_results)]
    shown = [l if len(l) <= 300 else l[:300] + ' [...]' for l in shown]
    log({'tool': 'grep', 'pattern': pattern, 'path': path, 'matches': n, 'returned': len(shown)})
    if r.returncode > 1:
        return 'error: ' + r.stderr.strip()[:300]
    head = f'{n} matching lines' + (f' (first {len(shown)} shown)' if n > len(shown) else '')
    return head + '\n' + '\n'.join(shown)


def list_dir(path='.'):
    p = resolve(path)
    if not os.path.isdir(p):
        return f'error: not a directory: {path}'
    out = []
    for name in sorted(os.listdir(p)):
        if name == '.git':
            continue
        full = os.path.join(p, name)
        out.append(name + '/' if os.path.isdir(full) else name)
    log({'tool': 'list_dir', 'path': path, 'entries': len(out)})
    return '\n'.join(out)


# ---------------- arm B ----------------

def describe(f):
    if f.get('declared') is not None:
        tag = ', '.join(f['declared'])
    else:
        why = ', '.join(f.get('impure_reasons', [])) or 'closure'
        inf = ', '.join(f['inferred']) or 'none'
        tag = f'UNTAGGED; inferred: {inf}; not machine-checkable because: {why}'
    return f'[{tag}] {f["signature"]}  // {f["file"]}:{f["line"]}  id={f["id"]}'


def signatures(pkg):
    pkg = pkg.strip().strip('/')
    fs = [f for f in GRAPH.values() if f['pkg'] == pkg and f['decl']]
    d = os.path.join(WORK, pkg)
    files = sorted(n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n))) if os.path.isdir(d) else []
    subdirs = sorted(n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n))) if os.path.isdir(d) else []
    log({'tool': 'signatures', 'pkg': pkg, 'functions': len(fs)})
    if not fs and not files and not subdirs:
        pkgs = sorted({f['pkg'] for f in GRAPH.values()})
        return f'error: unknown package "{pkg}". Packages: ' + ', '.join(pkgs)
    fs.sort(key=lambda f: (f['file'], f['line']))
    out = [f'package {pkg}: {len(fs)} declared functions',
           'files: ' + ', '.join(files),
           'subdirectories: ' + (', '.join(subdirs) or '(none)'), '']
    out += [describe(f) for f in fs]
    return '\n'.join(out)


def graph(function_id):
    f = GRAPH.get(function_id)
    if f is None:
        tail = function_id.split('.')[-1].strip('()*')
        cands = [i for i in GRAPH if i.endswith('.' + tail) or tail.lower() in i.lower()][:25]
        log({'tool': 'graph', 'id': function_id, 'found': False})
        return 'error: unknown function id. Did you mean:\n' + '\n'.join(cands)
    log({'tool': 'graph', 'id': function_id, 'found': True})
    keep = ['id', 'file', 'line', 'signature', 'exported', 'declared', 'inferred', 'inferred_approx', 'mut',
            'ambient', 'impure_reasons', 'direct', 'callers', 'callees', 'referenced_by', 'unresolved']
    return json.dumps({k: f[k] for k in keep if k in f and f[k] not in (None, [], '')}, indent=1)


def where(effect, pkg=None):
    effect = ' '.join(effect.split())
    hits = [f for f in GRAPH.values() if effect in f['inferred'] and (not pkg or f['pkg'] == pkg or f['pkg'].startswith(pkg.rstrip('/') + '/'))]
    hits.sort(key=lambda f: f['id'])
    log({'tool': 'where', 'effect': effect, 'pkg': pkg, 'hits': len(hits)})
    if not hits:
        effs = sorted({e for f in GRAPH.values() for e in f['inferred']})
        return 'no function has that effect' + (f' in {pkg}' if pkg else '') + '. Known effects: ' + ', '.join(effs)
    out = [f'{len(hits)} functions with effect "{effect}"' + (f' in {pkg}' if pkg else '') +
           ' (direct = the function itself contains the operation; otherwise it is reached through callees)']
    for f in hits:
        direct = any(d['effect'] == effect for d in f.get('direct', []))
        kind = 'closure' if not f['decl'] else 'func'
        out.append(f'{"direct " if direct else "via    "} {kind:7} {f["id"]}  // {f["file"]}:{f["line"]}')
    return '\n'.join(out)


S = lambda **props: {'type': 'object', 'properties': props, 'required': [k for k, v in props.items() if not v.pop('optional', False)]}
STR, INT = {'type': 'string'}, {'type': 'integer'}
COMMON = [
    ('open_file', 'Read a file from the repository, with line numbers. Give start_line and end_line to read part of it. At most 2000 lines per call. Every call is logged.',
     S(path=dict(STR), start_line=dict(INT, optional=True), end_line=dict(INT, optional=True)), open_file),
    ('edit', 'Replace one exact occurrence of old_text with new_text in a file. old_text must match exactly and be unique in the file.',
     S(path=dict(STR), old_text=dict(STR), new_text=dict(STR)), edit),
    ('create_file', 'Create a new file with the given content.', S(path=dict(STR), content=dict(STR)), create_file),
    ('check', f'Build the project and run its existing unit and integration tests. Returns the result. Limited to {CAP} calls per run.', S(), check),
    ('finish', 'Submit your change and end the run. Call this exactly once, when you are done.', S(summary=dict(STR, optional=True)), finish),
]
A_TOOLS = [
    ('grep', 'Search file contents with an extended regular expression (grep -rnE). path is a file or directory, default the repository root. graph.json is skipped unless path names it.',
     S(pattern=dict(STR), path=dict(STR, optional=True), max_results=dict(INT, optional=True)), grep),
    ('list_dir', 'List the entries of a directory.', S(path=dict(STR, optional=True)), list_dir),
]
B_TOOLS = [
    ('signatures', 'List every declared function in one package: its effect tag, signature, file and line, and function id. Also lists the files and subdirectories of that package directory.',
     S(pkg=dict(STR)), signatures),
    ('graph', 'Return the call-graph entry for one function id: its effects, where each direct effect happens, its callers, its callees, and which functions reference it as a value (for example route registration).',
     S(function_id=dict(STR)), graph),
    ('where', 'List every function that has a given effect, for example "writes users" or "net". Optionally restrict to a package (and its subpackages).',
     S(effect=dict(STR), pkg=dict(STR, optional=True)), where),
]
TOOLS = (B_TOOLS if ARM == 'B' else A_TOOLS) + COMMON
BYNAME = {t[0]: t for t in TOOLS}


def reply(i, result=None, error=None):
    msg = {'jsonrpc': '2.0', 'id': i}
    if error:
        msg['error'] = error
    else:
        msg['result'] = result
    sys.stdout.write(json.dumps(msg) + '\n')
    sys.stdout.flush()


for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    m = json.loads(raw)
    method, i = m.get('method'), m.get('id')
    if method == 'initialize':
        reply(i, {'protocolVersion': m['params'].get('protocolVersion', '2024-11-05'), 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'exp', 'version': '1'}})
    elif method == 'tools/list':
        reply(i, {'tools': [{'name': n, 'description': d, 'inputSchema': s} for n, d, s, _ in TOOLS]})
    elif method == 'tools/call':
        name, args = m['params']['name'], m['params'].get('arguments') or {}
        try:
            if finished:
                text = 'error: the run is over'
            else:
                text = BYNAME[name][3](**args)
        except Exception as e:  # report tool errors to the model rather than crashing the run
            text = f'error: {type(e).__name__}: {e}'
            log({'tool': name, 'exception': str(e)})
        log({'tool': '_result', 'name': name, 'chars': len(text)})
        reply(i, {'content': [{'type': 'text', 'text': text}], 'isError': text.startswith('error:')})
    elif method == 'ping':
        reply(i, {})
    elif i is not None:
        reply(i, error={'code': -32601, 'message': 'method not found'})
