# Report: checkpoint 2, harness built, acceptance tests written, shakedown done

Date: 2026-11-11. Stop point: before any scored run. The previous report is
`reports/checkpoint1.md`; the rulings it led to are in `DECISIONS.md`.

## Status against the thirteen rulings

| # | Ruling | State |
|---|---|---|
| 1 | Tag unexported named functions | Done. 1,304 of 1,454 declared functions tagged in source |
| 2 | edit + harness-taken diff | Done |
| 3 | No shell; check() in every arm, cap 10 | Done. check() takes 14 s |
| 4 | Three arms, tool sets as specified | Done, with two additions listed under "Deviations" |
| 5 | Task 6 reworded, path 7 counts, score 8 of 8 | Done |
| 6 | Drop Conduit; shakedown task 0, one run per arm | Done. All three runs correct |
| 7 | B's initial context: task, policies, package summary | Done. 6.7k tokens at B's first call |
| 8 | Same scoring sentence in every arm | Done |
| 9 | Context at finish primary, cumulative input secondary | Done |
| 10 | error.Error() ambient; `ambient` tag; `pure` means proven | Done |
| 11 | Checker fails closed on reflection and subprocess | Done. Mutation test now 12 of 12 |
| 12 | Executable acceptance tests for tasks 1 to 6 | Written. **Not validated against a correct solution** (see below) |
| 13 | Integration tests three times | 102 of 102 passed in all three runs. Nothing excluded |

## Decisions needed before scored runs

1. **Task 3 is already implemented in Miniflux.** `EntryAuthor=<regex>` is a supported rule in
   `block_filter_entry_rules` at the pinned commit (`internal/reader/filter/filter.go:204`). The
   acceptance test for task 3 passes on the unmodified tree. The task needs replacing or
   dropping; as written it would score every arm correct for doing nothing.
2. **Interface lines added to tasks 1, 2, 4 and 5.** The original task text does not name the
   new field or route, so a test written "from the task text only" has nothing fixed to call. I
   added one **Interface** paragraph to each (see `TASKS.md`): `refresh_interval` in minutes,
   `word_count`, `POST /v1/api-keys/{apiKeyID}/regenerate`, `fetch_timeout` in seconds. Every arm
   gets the same text. Approve, or change the names and I will update tests to match.
3. **The acceptance tests have only been proven to fail.** Each of tasks 1, 2, 4, 5, 6 fails on
   the unmodified tree for the intended reason, and the task 0 test passed on three independent
   real solutions. No test for tasks 1 to 6 has been run against a correct implementation,
   because none exists yet. The risk is a test that rejects a correct change. The two most
   exposed are task 1 (expects `next_check_at` to be 137 minutes ahead, within 3) and task 5
   (timing windows around a 6-second slow server). Options: (a) I write reference solutions for
   those tasks first, which also gives the "minimal correct diff" the blast-radius metric needs;
   (b) run as is and I hand-review every acceptance failure before it is scored. I recommend (a)
   for tasks 1, 5 and 6.
4. **Escalation for B.** The original design gives B one escalation with free file access after
   a failed first attempt. The harness does not implement it. With check() now available in every
   arm, does it still apply, and if so what triggers it: a failed acceptance test, which B cannot
   see?
5. **Hand-tag list.** 150 declared functions are untagged (77 exported, 73 unexported). Nobody
   has hand-tagged them. B is shown them as `UNTAGGED; inferred: ...; not machine-checkable
   because: ...`. Run as is, or hand-tag first?

## Deviations from the rulings, for you to accept or reverse

- **A1's tree contains `graph.json` and the `.agentpolicy` files**, not only the tags. A1 can
  open and grep them like any file. Reasoning: A1 then has everything B has plus free access, so
  B against A1 isolates the restriction. Remove them if "annotated tree" meant tags only.
- **`signatures(pkg)` also lists the file and subdirectory names of that package directory.**
  Without it B has no way to learn the path of a non-Go file, and task 1 requires editing an HTML
  template and translation files. The original design gave B "the list of files"; ruling 7
  removed the inline index, so I moved the file names into this tool.
- **"process-control" was split.** Ruling 11 names reflection and process-control. My
  process-control category also held `os.Exit`, flag parsing and signal handling, which do not
  defeat the analysis. Only `reflection` and a new `subprocess` category (os/exec, fork/exec)
  fail closed. No Miniflux function is in either.
- **Temperature** cannot be set through the CLI. All arms use the same default.
- **The plain and annotated trees differ by 8 lines beyond the tags**: gofmt realigned a few
  one-line method declarations once comment lines were inserted between them.

## Correction to checkpoint 1

I wrote that the 22 `http/response` helpers were blocked only by an `error.Error()` call. That
was wrong. Making `error.Error()` ambient did not clear them. Their actual blockers are a call
through a compression-writer interface that the call graph cannot resolve, and a builder pointer
returned from a constructor, which the tool cannot prove is freshly allocated. They remain on the
hand-tag list.

## Tag state after rulings 1, 10 and 11

| Declared functions | Count |
|---|---|
| Tagged with effects | 698 |
| `pure` (proven) | 515 |
| `ambient` | 91 |
| Untagged, hand-tag list | 150 |
| Total | 1,454 (885 exported, 569 unexported) |

Reasons on the hand-tag list (a function can have several): unresolved dynamic call 72, write
through a pointer of unknown origin 65, reads a reassigned package variable 42, writes a package
variable 12, reads process environment 8, process control 6, table-less database call 5, metrics
3, unknown external call 3. List: `out/miniflux-untagged.json`.

Checker: 0 tag failures. Policy row zero is unchanged from checkpoint 1 (59 hits, 29 pairs).

## Harness

Each run is `python3 harness/run.py <arm> <task> <n>`:

1. Fresh git worktree at the pinned commit: `1af9501` for A0, branch `annotated` for A1 and B.
2. `claude -p` with `--model claude-fable-5-2`, the arm's system prompt replacing the default,
   built-in tools disabled, user settings and plugins not loaded, and one tool server
   (`harness/mcp_server.py`). Verified from the run's init event: the only tools present are the
   arm's own. Working directory is an empty folder.
3. When the model stops, the harness takes `git diff`, runs the existing suite, runs the hidden
   acceptance test, and writes one row to the results sheet.

**Tools**

| Arm | Locating code | Common to all |
|---|---|---|
| A0, A1 | `open_file`, `grep`, `list_dir` | `edit`, `create_file`, `check` (cap 10), `finish` |
| B | `signatures(pkg)`, `graph(function_id)`, `where(effect, pkg?)`, `open_file` | same |

**Prompts.** Exact text for each arm of the shakedown is in
`runs/task0-<arm>-1/system_prompt.txt` and `user_prompt.txt`; the source is `harness/prompts.py`.
The system prompt is the same in all arms except the access paragraph. A1 and B share the same
description of the layer. B's user prompt adds 41 policy lines and an 86-line package summary.

**Correct** means: existing unit and integration suite passes, and every gating check of the
hidden acceptance test passes.

## Acceptance tests (`acceptance/`)

Python, run against a real server built from the run's tree, a fresh Postgres database, and a
local RSS server the test controls (items, delay, status code). No internet.

| Task | What the test does |
|---|---|
| 0 | Count endpoint returns 3 for a 3-entry feed; 404 for unknown feed and for another user's feed |
| 1 | New column on `feeds`; `refresh_interval` readable, writable, persisted; input present in the UI edit form; after a refresh `next_check_at` is 137 min ahead for the overridden feed and not for a plain one |
| 2 | Entries are first created by the unmodified binary, then the modified binary migrates the same database: old entry is null or 4; new entries are 7 and 3; single-entry endpoint has the field |
| 3 | Feed with `EntryAuthor=^Blocked Bob$` stores only the other author's entry |
| 4 | Old token works, regenerate returns a different token, old token gets 401, new token gets 200 |
| 5 | Global 30 s, per-feed 2 s, server sleeps 6 s: override feed fails in 1.5 to 5 s, plain feed succeeds. Then global 3 s, per-feed 20 s: override feed succeeds |
| 6 | Row count of `audit_log` before and after each of the 8 ground-truth requests; path 7 is exercised on both its success and its fetch-failure writer. Records paths found out of 8. Non-gating: two GETs add no rows |

## Shakedown (task 0, unscored, one run per arm)

| Arm | Correct | Context at finish | Cumulative input | Output tokens | Tool calls | Files opened | Lines read | check() | Cost | Wall |
|---|---|---|---|---|---|---|---|---|---|---|
| A0 | yes | 8,751 | 35,655 | 2,030 | 9 | 3 | 254 | 1 | $0.21 | 44 s |
| A1 | yes | 11,349 | 55,502 | 2,974 | 14 | 5 | 228 | 1 | $0.29 | 51 s |
| B | yes | 22,409 | 86,531 | 2,141 | 10 | 4 | 274 | 1 | $0.46 | 44 s |

One run per arm on a two-file change, so this says the harness works, not which arm is better.
Three things it did show:

- **B started at 6.7k tokens and A0 at 2.0k.** The policies and package summary cost about 4.3k
  before B does anything.
- **B's tool results were three times the size of A0's** (29.6k characters against 9.7k). Most of
  that is one `signatures(internal/api)` call: 64 functions, each with a tag that can list a
  dozen effects. On a small task the layer costs more context than grep does. Whether that
  reverses on tasks with cross-module reach is what the scored runs test.
- **B opened one more file than A0** and read about the same number of lines. The restriction did
  not reduce reading here.

B also wrote an `@effects` tag on the handler it added, unprompted, and the tag was correct.

Sheet: `results/shakedown.csv`. Per run: `runs/task0-*/` (prompts, full model stream, tool log,
diff, suite output, acceptance result).

## What scored runs will cost

Shakedown runs cost $0.21 to $0.46 each at list price and took under a minute. Tasks 1 to 6 are
larger. With task 3 unresolved there are 5 tasks x 3 arms x 3 repeats = 45 runs (54 with a
replacement task 3). Three runs in parallel worked without port or database collisions.

## Files added since checkpoint 1

| Path | What |
|---|---|
| `DECISIONS.md` | Rulings |
| `TASKS.md` | Exact task text per task, with the proposed Interface lines |
| `harness/mcp_server.py`, `run.py`, `prompts.py`, `check.sh` | Tool server, runner, prompts, build-and-test |
| `acceptance/lib.py`, `tests.py`, `run.py` | Hidden acceptance tests |
| `results/shakedown.csv`, `runs/task0-*/` | Shakedown results and artifacts |
| `baseline/miniflux-integration-run{1,2,3}.txt` | The three integration runs |
| `reports/checkpoint1.md` | Previous report |
