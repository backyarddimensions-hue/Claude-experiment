"""Prompts. The system prompt is identical across arms except for the ACCESS block."""
import json, os, collections

SYSTEM = """You are making one change to Miniflux, a feed reader written in Go and backed by PostgreSQL.

You work only through the tools provided. There is no shell.

{access}

Tools every run has:
- open_file(path, start_line, end_line): read a file or part of one. Every call is logged.
- edit(path, old_text, new_text) and create_file(path, content): make the change.
- check(): build the project and run its existing unit and integration tests. At most 10 calls.
- finish(): submit. Call it once, when the change is complete.

The existing tests must still pass. They do not cover the new behaviour: after you finish, hidden
acceptance tests are run against your change.

Correctness is scored first, context used second."""

ACCESS_A0 = """Access: you can read any file in the repository with open_file, search file contents with
grep(pattern, path), and list directories with list_dir(path)."""

LAYER = """The repository carries an annotation layer:
- Every declared function has a comment `// @effects: ...` directly above it. The tag lists what
  the function does, directly or through anything it calls:
    pure                 proven to have no effects
    ambient              only logging, clock, concurrency or stream/HTTP-response output
    reads <table>        reads that database table
    writes <table>       writes that database table
    net                  makes outbound network calls
    fs                   touches the filesystem
    mut                  mutates its receiver or an argument
  A function with no tag could not be machine-checked (it uses global state or a call that cannot
  be resolved); treat its effects as unknown.
- Each package directory has, or inherits from a parent directory, a `.agentpolicy` file: `nouns`
  (the tables the package may touch), `priority`, and `boundary` (ingress, egress, interior or
  storage).
- A call graph records, for every function, its callers, its callees, where each direct effect
  happens, and which functions reference it as a value (for example route registration)."""

ACCESS_A1 = LAYER + """

Access: you can read any file in the repository with open_file, search file contents with
grep(pattern, path), and list directories with list_dir(path). The call graph is the file
`graph.json` at the repository root. grep skips graph.json unless its path argument names that
file."""

ACCESS_B = LAYER + """

Access: you cannot list or search the repository. You are given the task, every policy file, and a
summary of every package. To find code, use:
- signatures(pkg): every function in a package with its effect tag, signature, file and line, plus
  the names of the files and subdirectories in that package directory.
- graph(function_id): callers, callees and effects of one function.
- where(effect, pkg): every function with a given effect, optionally within one package.
Read function bodies and other files with open_file."""

ACCESS = {'A0': ACCESS_A0, 'A1': ACCESS_A1, 'B': ACCESS_B}


def system(arm):
    return SYSTEM.format(access=ACCESS[arm])


def b_context(work, graph_path):
    F = json.load(open(graph_path))['functions']
    pk = collections.defaultdict(lambda: [0, set()])
    for f in F:
        if f['decl']:
            pk[f['pkg']][0] += 1
            pk[f['pkg']][1].update(f['inferred'])
    order = {'reads': 0, 'writes': 1, 'net': 2, 'fs': 3, 'mut': 4}
    lines = ['## Packages (number of declared functions; union of their effects)']
    for p in sorted(pk):
        n, effs = pk[p]
        e = ', '.join(sorted(effs, key=lambda x: (order[x.split()[0]], x))) or 'no effects'
        lines.append(f'{p} ({n}): {e}')
    pol = ['## Policy files (a package without its own file inherits from the nearest parent)']
    for root, dirs, files in os.walk(work):
        dirs[:] = sorted(d for d in dirs if d != '.git')
        if '.agentpolicy' in files:
            body = ' | '.join(l.strip() for l in open(os.path.join(root, '.agentpolicy')) if l.strip())
            pol.append(f'{os.path.relpath(root, work)}: {body}')
    return '\n'.join(pol) + '\n\n' + '\n'.join(lines)


def task_text(task):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    md = open(os.path.join(here, 'TASKS.md')).read()
    sec = md.split(f'## Task {task}')[1].split('\n## ')[0]
    body = sec.split('\n', 1)[1]
    keep = []
    for para in body.strip().split('\n\n'):
        if para.startswith('(') or para.startswith('Miniflux at the pinned commit'):
            continue          # notes for the experimenters, not for the agent
        para = para.replace('**Interface:** ', '')
        keep.append(para[0].upper() + para[1:])
    return '\n\n'.join(keep)


def user(arm, task, work, graph_path):
    t = 'Task:\n\n' + task_text(task)
    if arm == 'B':
        t += '\n\n' + b_context(work, graph_path)
    return t
