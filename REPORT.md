# Report: checkpoint 3, the 54 scored runs

Date: 2026-11-12. Earlier reports: `reports/checkpoint1.md`, `reports/checkpoint2.md`. Rulings:
`DECISIONS.md`.

## Result

**All 54 runs are correct.** Every arm passed the existing suite and every gating acceptance
check on every task, 3 of 3. There are no failures to classify.

**The predicted context saving did not appear.** Measured against the criteria written before
the runs:

| Criterion (Experiment1.txt) | Outcome |
|---|---|
| B within ten points of A on correctness | Met: 100% in every arm on every task |
| B uses less than half the input tokens | Not met on any task. B used more context than A0 on five tasks and less on one |
| B opens fewer than half the files | Not met on any task. B opened between 0.87 and 1.33 times as many files as A0 |

So the outcome is neither "thesis supported" nor "thesis weakened" as those were defined.
Correctness held under restriction, but restriction plus the layer did not make the work
cheaper; on most tasks it made it more expensive.

Two limits on reading this:

- **Correctness is at ceiling.** With 54 of 54 correct, the tasks cannot show a correctness
  difference between arms in either direction. They were not hard enough for this model.
- **Three runs per cell.** Where the ranges of two arms overlap, I do not claim a difference.

## Context by task

Median of three runs. Ratios are B divided by A0.

| Task | A0 context at finish | A1 | B | B / A0 | Do the B and A0 ranges overlap? | B / A0 files opened | B / A0 lines read |
|---|---|---|---|---|---|---|---|
| 1 per-feed fetch interval | 58,710 | 70,254 | 98,865 | 1.68 | no, B higher | 1.18 | 1.17 |
| 2 entry word count | 37,590 | 38,712 | 53,830 | 1.43 | no, B higher | 1.33 | 0.76 |
| 3 per-user feed limit | 57,290 | 62,314 | 81,519 | 1.42 | yes | 0.92 | 0.87 |
| 4 rotate API keys | 19,036 | 18,250 | 23,892 | 1.26 | yes | 1.00 | 1.59 |
| 5 fetch timeout per feed | 37,163 | 39,606 | 58,453 | 1.57 | no, B higher | 0.89 | 1.41 |
| 6 audit log | 75,189 | 81,931 | 60,725 | 0.81 | yes | 0.87 | 0.59 |

- On tasks 1, 2 and 5 B's context was higher than A0's in every run.
- On tasks 3 and 4 B's median was higher but the ranges overlap.
- On task 6, the task built to test the thesis, B's median was lower (0.81 of A0, 0.74 of A1) and
  B read 41% fewer lines. The ranges overlap: one A0 run finished at 39,564 tokens after opening
  7 files, below every B run. Three runs cannot separate these.
- A1 (tags present, free access) finished between 0.96 and 1.20 times A0's context. The layer
  did not reduce A1's cost on any task.

## Why B cost more: where the tool output went

Characters returned by tools, median per run, in thousands.

| Task | A0 total (grep + open_file) | B total | B: `signatures` | B: `open_file` | B: `graph` + `where` |
|---|---|---|---|---|---|
| 1 | 85 (21 + 66) | 156 | 68 | 85 | 11 |
| 2 | 62 (25 + 34) | 90 | 62 | 26 | 0 |
| 3 | 91 (19 + 71) | 136 | 64 | 61 | 6 |
| 4 | 29 (19 + 9) | 32 | 14 | 17 | 2 |
| 5 | 57 (17 + 38) | 100 | 49 | 57 | 4 |
| 6 | 110 (23 + 81) | 80 | 15 | 50 | 5 |

- **`signatures(pkg)` is B's main cost.** On tasks 1, 2, 3 and 5 it returned 49k to 68k
  characters per run, two to three times what A0 spent on grep. One call on `internal/storage`
  or `internal/ui` lists well over a hundred functions, each with a tag that can name a dozen
  tables.
- **B did not read fewer file bodies.** Its `open_file` volume was about the same as A0's on
  tasks 1, 3 and 5. The index was paid for on top of the reading, not instead of it.
- **Task 6 is where it reversed.** B used `where("writes users")` and `where("writes feeds")`
  (4 to 7 calls, about 5k characters) and then opened 38% less file text than A0. This is the
  one task whose question is "which functions have this effect", which is what the layer
  answers directly.
- B also starts 4,700 tokens behind: its first call is 6,694 tokens against A0's 2,018, for the
  policies and package summary.

This points at the index being too verbose rather than at the idea being wrong, but that is an
inference from one design of `signatures`, not something these runs tested.

## Task 6 in detail

- Paths found out of 8: A0 8, 8, 8; A1 8, 8, 8; B 8, 8, 8. Every run logged exactly one row for
  each of the nine test requests, including both writers of the refresh path.
- Non-gating check: no run added audit rows for read-only requests. Nobody took the
  log-everything shortcut.
- A1 opened or searched `graph.json` in 2 of its 3 task-6 runs, and in no run of any other task.
- The unrestricted arms found all eight paths with grep. The effect tags were not needed to
  find them; on this evidence they made finding them somewhat cheaper for B.

## Task 3 non-gating check

`CreateFeedFromSubscriptionDiscovery` is covered in 9 of 9 runs. I read the diffs: every run
enforces the limit inside `storage.CreateFeed`, where the single INSERT into `feeds` lives, so
the discovery path, the web UI and the Google Reader API are covered whichever handler calls it.
Several runs also added an early check in the API handler. This was established from the diffs,
not by exercising the discovery route.

## B and untagged functions (ruling 5)

Per run, functions on the hand-tag list that B queried with `graph` / opened with `open_file`:

| Task | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| 1 | 0 / 0 | 0 / 0 | 0 / 0 |
| 2 | 0 / 4 | 1 / 2 | 0 / 2 |
| 3 | 0 / 0 | 0 / 0 | 0 / 0 |
| 4 | 0 / 0 | 0 / 0 | 0 / 0 |
| 5 | 0 / 0 | 0 / 0 | 0 / 0 |
| 6 | 0 / 5 | 0 / 1 | 0 / 5 |

"Opened" means the range B read overlapped the function, which includes reading a whole file
that happens to contain one. All of these runs were correct, so the untagged functions cost
nothing measurable here.

## Other observations

- **Tools.** B called `graph` in 12 of 18 runs, but its output was small (0 to 7k characters
  per run). Most of B's locating was done with `signatures`, and with `where` on task 6.
- **Layer upkeep.** B and A1 runs updated or added `@effects` comments on functions they
  changed, without being asked. I did not run the checker over the 36 annotated-tree diffs, so I
  cannot say how many of those tags are correct.
- **Blast radius.** Diffs touched 0 to 3 files outside the reference set on tasks 1 to 5 in every
  arm, mostly `client/model.go` and a test file. On task 6 it was 0 to 8 with no arm standing out;
  designs differed (the reference threads an opt-in through storage, most runs added an audit
  helper and called it from handlers).
- **check().** 47 runs called it once, 7 called it twice, none more. The cap of 10 never bound.
- **Validity.** No run timed out, hit a rate limit or was repeated. All 54 called `finish`.

## Per-task tables

Correct means existing suite passes and every gating acceptance check passes. Cost is list price
as reported by the CLI.
### Task 1: per-feed fetch interval

| Arm | Correct | Context at finish (median; range) | Cumulative input (median) | Files opened (median; range) | Lines read (median) | Tool calls (median) | check() (median) | Diff files (median; reference 32) | Cost (median) |
|---|---|---|---|---|---|---|---|---|---|
| A0 | 3 of 3 | 58,710; 56,781-69,412 | 396,712 | 11; 10-12 | 1,788 | 67 | 1 | 34 | $1.64 |
| A1 | 3 of 3 | 70,254; 59,479-71,683 | 427,040 | 10; 10-14 | 1,300 | 97 | 1 | 34 | $2.02 |
| B | 3 of 3 | 98,865; 88,222-108,646 | 549,902 | 13; 12-15 | 2,084 | 97 | 1 | 34 | $2.39 |

B and untagged functions (queried / opened per run): 0 / 0, 0 / 0, 0 / 0

Files touched outside the reference set (per run): A0: 2, 2, 2; A1: 1, 2, 2; B: 2, 2, 2

### Task 2: entry word count

| Arm | Correct | Context at finish (median; range) | Cumulative input (median) | Files opened (median; range) | Lines read (median) | Tool calls (median) | check() (median) | Diff files (median; reference 5) | Cost (median) |
|---|---|---|---|---|---|---|---|---|---|
| A0 | 3 of 3 | 37,590; 32,998-38,017 | 194,284 | 6; 6-7 | 1,094 | 33 | 1 | 5 | $0.81 |
| A1 | 3 of 3 | 38,712; 38,408-40,290 | 237,097 | 8; 6-8 | 1,156 | 38 | 1 | 5 | $0.90 |
| B | 3 of 3 | 53,830; 47,831-64,803 | 368,798 | 8; 6-9 | 826 | 33 | 1 | 5 | $1.09 |

B and untagged functions (queried / opened per run): 0 / 4, 1 / 2, 0 / 2

Files touched outside the reference set (per run): A0: 1, 1, 1; A1: 1, 1, 1; B: 1, 1, 0

### Task 3: per-user feed limit

| Arm | Correct | Context at finish (median; range) | Cumulative input (median) | Files opened (median; range) | Lines read (median) | Tool calls (median) | check() (median) | Diff files (median; reference 8) | Cost (median) |
|---|---|---|---|---|---|---|---|---|---|
| A0 | 3 of 3 | 57,290; 47,988-60,039 | 332,119 | 12; 10-13 | 2,062 | 54 | 1 | 10 | $1.45 |
| A1 | 3 of 3 | 62,314; 52,792-64,533 | 331,692 | 10; 9-10 | 1,949 | 48 | 1 | 9 | $1.58 |
| B | 3 of 3 | 81,519; 54,366-85,354 | 489,218 | 11; 9-13 | 1,784 | 50 | 1 | 9 | $1.81 |

B and untagged functions (queried / opened per run): 0 / 0, 0 / 0, 0 / 0

Files touched outside the reference set (per run): A0: 2, 2, 2; A1: 3, 1, 0; B: 0, 2, 1

### Task 4: rotate API keys

| Arm | Correct | Context at finish (median; range) | Cumulative input (median) | Files opened (median; range) | Lines read (median) | Tool calls (median) | check() (median) | Diff files (median; reference 3) | Cost (median) |
|---|---|---|---|---|---|---|---|---|---|
| A0 | 3 of 3 | 19,036; 18,915-20,153 | 102,012 | 4; 4-5 | 294 | 16 | 1 | 4 | $0.44 |
| A1 | 3 of 3 | 18,250; 15,397-21,630 | 86,397 | 4; 4-5 | 473 | 16 | 1 | 4 | $0.43 |
| B | 3 of 3 | 23,892; 18,870-29,104 | 89,164 | 4; 4-5 | 467 | 13 | 1 | 3 | $0.40 |

B and untagged functions (queried / opened per run): 0 / 0, 0 / 0, 0 / 0

Files touched outside the reference set (per run): A0: 1, 1, 1; A1: 0, 1, 1; B: 0, 0, 1

### Task 5: fetch timeout per feed

| Arm | Correct | Context at finish (median; range) | Cumulative input (median) | Files opened (median; range) | Lines read (median) | Tool calls (median) | check() (median) | Diff files (median; reference 8) | Cost (median) |
|---|---|---|---|---|---|---|---|---|---|
| A0 | 3 of 3 | 37,163; 23,885-38,335 | 170,905 | 9; 5-9 | 1,036 | 33 | 1 | 9 | $0.89 |
| A1 | 3 of 3 | 39,606; 35,449-51,045 | 209,599 | 9; 7-10 | 1,141 | 35 | 1 | 9 | $0.96 |
| B | 3 of 3 | 58,453; 55,304-63,049 | 393,801 | 8; 8-8 | 1,464 | 34 | 1 | 7 | $1.17 |

B and untagged functions (queried / opened per run): 0 / 0, 0 / 0, 0 / 0

Files touched outside the reference set (per run): A0: 0, 1, 1; A1: 1, 1, 1; B: 1, 1, 1

### Task 6: audit log

| Arm | Correct | Context at finish (median; range) | Cumulative input (median) | Files opened (median; range) | Lines read (median) | Tool calls (median) | check() (median) | Diff files (median; reference 8) | Cost (median) |
|---|---|---|---|---|---|---|---|---|---|
| A0 | 3 of 3 | 75,189; 39,564-81,296 | 422,321 | 15; 7-16 | 2,646 | 66 | 1 | 12 | $2.11 |
| A1 | 3 of 3 | 81,931; 72,056-93,456 | 490,104 | 15; 15-16 | 2,893 | 71 | 1 | 11 | $2.21 |
| B | 3 of 3 | 60,725; 57,079-83,225 | 365,772 | 13; 12-14 | 1,553 | 71 | 1 | 11 | $1.71 |

Paths found out of 8: A0: 8, 8, 8; A1: 8, 8, 8; B: 8, 8, 8

B and untagged functions (queried / opened per run): 0 / 5, 0 / 1, 0 / 5

Files touched outside the reference set (per run): A0: 5, 0, 8; A1: 6, 6, 3; B: 5, 7, 6

## Before the runs: what changed since checkpoint 2

- Task 3 replaced with the per-user feed limit, and its test written, before any reference
  existed.
- Reference solutions written for all six tasks by separate agents (`reference/`). All six
  acceptance tests passed against their references as first written; I re-ran each twice
  myself with the same result. **No test was changed.** The log is in `reference/README.md`.
- No acceptance failure occurred in the scored runs, so the hand-review backstop was not
  triggered.
- grep skips `graph.json` unless named; A1's prompt says so.

## Cost and time

54 runs, 46 minutes wall clock at three in parallel, $70.71 at list price. Median run 107 s,
longest 211 s.

## Files

| Path | What |
|---|---|
| `results/results.csv` | One row per scored run |
| `results/per-task.md`, `results/analyze.py` | The tables above and the script that makes them |
| `results/batch.log` | Run order and one summary line per run |
| `runs/task<T>-<arm>-<n>/` | Prompts, model stream, tool log, diff, suite output, acceptance result |
| `reference/` | Reference diffs and the test change log |
| `TASKS.md` | Exact task text |
