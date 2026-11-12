#!/usr/bin/env python3
"""Plant undeclared effects in a copy of the tagged Miniflux tree and see whether the checker fails.

Each mutation adds a helper file plus one call from an exported function whose existing tag
does NOT declare the planted effect. "caught" = check.py reports an undeclared write/net for that
function (or flags it as no longer provably pure).
"""
import subprocess, shutil, os, json, sys
EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(EXP, 'repos/miniflux')
WORK = sys.argv[1]
ST, UR = 'internal/storage', 'internal/urllib'
HOOK_ST = ('internal/storage/category.go', '\tvar result bool\n\tquery := `SELECT true FROM categories WHERE user_id=$1 AND id=$2 LIMIT 1`',
           'internal/storage.(*Storage).CategoryIDExists')
HOOK_UR = ('internal/urllib/url.go', 'func IsAbsoluteURL(inputURL string) bool {\n', 'internal/urllib.IsAbsoluteURL')
M = [
 ('M1 direct SQL write in a reads-only function', HOOK_ST, 'zzMut(s, categoryID)', ST,
  'package storage\nfunc zzMut(s *Storage, id int64) { s.db.Exec(`UPDATE users SET last_login_at=now() WHERE id=$1`, id) }\n', 'writes users'),
 ('M2 outbound HTTP two calls deep under a pure function', HOOK_UR, 'zzMut()', UR,
  'package urllib\nimport "net/http"\nfunc zzMut() { zzInner() }\nfunc zzInner() { http.Get("http://example.org/") }\n', 'net'),
 ('M3 write through a module interface satisfied by *sql.DB', HOOK_ST, 'zzMut(s.db, categoryID)', ST,
  'package storage\nimport "database/sql"\ntype zzExecer interface{ Exec(string, ...any) (sql.Result, error) }\nfunc zzMut(e zzExecer, id int64) { e.Exec(`DELETE FROM feeds WHERE id=$1`, id) }\n', 'writes feeds'),
 ('M4 write through a function value held in a package variable', HOOK_ST, 'zzHook(s, categoryID)', ST,
  'package storage\nvar zzHook = func(s *Storage, id int64) { s.db.Exec(`DELETE FROM entries WHERE id=$1`, id) }\n', 'writes entries'),
 ('M5 write whose table name is only known at run time', HOOK_ST, 'zzMut(s, zzTable())', ST,
  'package storage\nimport "os"\nfunc zzTable() string { return os.Getenv("T") }\nfunc zzMut(s *Storage, t string) { s.db.Exec("DELETE FROM " + t) }\n', 'writes ?'),
 ('M6 statement prepared elsewhere, executed here', HOOK_ST, 'zzStmt.Exec(categoryID)', ST,
  'package storage\nimport "database/sql"\nvar zzStmt *sql.Stmt\nfunc ZZPrepare(s *Storage) { zzStmt, _ = s.db.Prepare(`UPDATE feeds SET disabled=true WHERE id=$1`) }\n', 'writes feeds'),
 ('M7 write via reflection', HOOK_ST, 'zzMut(s)', ST,
  'package storage\nimport "reflect"\nfunc zzMut(s *Storage) { reflect.ValueOf(s.db).MethodByName("Exec").Call([]reflect.Value{reflect.ValueOf("DELETE FROM users")}) }\n', 'writes users'),
 ('M8 outbound HTTP in a goroutine', HOOK_UR, 'zzMut()', UR,
  'package urllib\nimport "net/http"\nfunc zzMut() { go func() { http.Get("http://example.org/") }() }\n', 'net'),
 ('M9 SQL text built with Sprintf and passed through a helper', HOOK_ST, 'zzMut(s, categoryID)', ST,
  'package storage\nimport "fmt"\nfunc zzRun(s *Storage, q string, id int64) { s.db.Exec(q, id) }\nfunc zzMut(s *Storage, id int64) { zzRun(s, fmt.Sprintf(`UPDATE %s SET title=$1`, "categories"), id) }\n', 'writes categories'),
 ('M10 write by shelling out to psql', HOOK_ST, 'zzMut()', ST,
  'package storage\nimport "os/exec"\nfunc zzMut() { exec.Command("psql", "-c", "DELETE FROM users").Run() }\n', 'writes users'),
 ('M11 outbound call through a custom http.RoundTripper', HOOK_UR, 'zzMut()', UR,
  'package urllib\nimport "net/http"\nfunc zzMut() { var rt http.RoundTripper = http.DefaultTransport; r, _ := http.NewRequest("GET", "http://example.org/", nil); rt.RoundTrip(r) }\n', 'net'),
 ('M12 file write under a pure function', HOOK_UR, 'zzMut()', UR,
  'package urllib\nimport "os"\nfunc zzMut() { os.WriteFile("/tmp/x", nil, 0o600) }\n', 'fs'),
]
rows = []
for name, (path, anchor, fid), call, pkgdir, helper, want in M:
    shutil.rmtree(WORK, ignore_errors=True)
    shutil.copytree(SRC, WORK, ignore=shutil.ignore_patterns('.git'))
    p = os.path.join(WORK, path); s = open(p).read()
    assert anchor in s, name
    if anchor.endswith('{\n'):
        s = s.replace(anchor, anchor + '\t' + call + '\n', 1)
    else:
        s = s.replace(anchor, '\t' + call + '\n' + anchor, 1)
    open(p, 'w').write(s)
    open(os.path.join(WORK, pkgdir, 'zz_mut.go'), 'w').write(helper)
    g = os.path.join(WORK, 'graph.json')
    r = subprocess.run([os.path.join(EXP, 'tools/effects-bin'), '-dir', WORK, '-out', g], capture_output=True, text=True)
    if r.returncode:
        rows.append((name, want, 'BUILD ERROR', r.stderr[-300:])); continue
    res = os.path.join(WORK, 'res.json')
    c = subprocess.run(['python3', os.path.join(EXP, 'scripts/check.py'), g, os.path.join(EXP, 'policies/miniflux'), '--json', res], capture_output=True, text=True)
    fails = [x for x in json.load(open(res))['tag_failures']]
    mine = [x for x in fails if x[0] == fid]
    f = next(x for x in json.load(open(g))['functions'] if x['id'] == fid)
    if mine and mine[0][1] == 'undeclared' and want in mine[0][2]:
        verdict = 'caught (exact effect)'
    elif mine and mine[0][1] == 'undeclared':
        verdict = 'caught as ' + ','.join(mine[0][2])
    elif mine:
        verdict = 'caught indirectly: ' + mine[0][1]
    elif want in f['inferred']:
        verdict = 'inferred but checker does not fail on this effect type'
    else:
        verdict = 'MISSED'
    rows.append((name, want, verdict, f'checker exit {c.returncode}, {len(fails)} failing functions; impurity noted: {f.get("impure_reasons")}'))
shutil.rmtree(WORK, ignore_errors=True)
json.dump(rows, open(os.path.join(EXP, 'out/mutation-results.json'), 'w'), indent=1)
for r in rows:
    print(f'{r[0]:62} want={r[1]:18} -> {r[2]}\n      {r[3]}')
