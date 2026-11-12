# Decisions

## Rulings on checkpoint 1 (from Fable, 2026-11-11)

Answers to the five questions in REPORT.md:

1. Unexported named functions: include, and tag them in source too. Handlers without tags are a
   hole in the layer. Closures stay excluded.
2. edit + harness-taken git diff: yes.
3. Feedback: option (b). No shell in any arm. All arms get check() (build + existing tests),
   counted, cap 10.
4. Three arms on Miniflux: A0 plain tree, A1 annotated tree, B annotated + restricted.
   A0/A1 tools: open_file, grep, list_dir. B tools: signatures(pkg), graph(function_id),
   where(effect, pkg?), open_file (logged).
5. Path 7 counts. Reword task 6: "Every API request that modifies a row in users or feeds must
   append a row to audit_log. The only exception is the last-login timestamp updated during
   authentication." Score pass/fail on all 8, and record how many of 8 were found.

Changes:

6. Drop Conduit. Add an unscored shakedown task 0 on Miniflux, 1 run per arm.
7. B's initial context: task, policies, per-package summary (function count, union of effects).
   No full index inline.
8. Same sentence in every arm's prompt: "Correctness is scored first, context used second."
   Remove "open only what you need" from B.
9. Primary context metric: context size at finish. Cumulative input tokens secondary.
10. error.Error() is ambient. Ambient-only functions get the tag `ambient`; `pure` means proven
    pure.
11. Checker fails closed: reflection or process-control means the function cannot be certified
    and goes to the hand-tag list.
12. Write executable acceptance tests for tasks 1-6 before any run, from the task text only.
    Hidden from all arms.
13. Run Miniflux integration tests three times; exclude anything flaky.

Next stop: harness built, acceptance tests written, shakedown done. Push and stop before scored
runs.

## Rulings on checkpoint 2 (from Fable, 2026-11-11)

Answers to the five questions in REPORT.md:

1. Replace task 3 with "per-user feed limit":
   "Add a per-user limit on the number of feeds. Interface: the user object has an integer field
   `max_feeds`; 0 means unlimited. Only an administrator can change it, with
   `PUT /v1/users/{userID}`. Once a user has `max_feeds` feeds, no request may create another one
   for that user: `POST /v1/feeds` returns a 4xx status and creates nothing, and `POST /v1/import`
   never leaves the user with more than `max_feeds` feeds."
   Gating checks: field readable and admin-settable; non-admin cannot change own limit; create
   beyond limit is 4xx with no new row; import at limit adds nothing; import below limit still
   works. Non-gating, from the diff: whether CreateFeedFromSubscriptionDiscovery is covered.
2. Interface lines for tasks 1, 2, 4, 5: approved as written.
3. Write reference solutions for all six tasks, on a branch no arm can reach, before any scored
   run. Change a test only when the reference shows the test is wrong, and log each change.
   Backstop: hand-review every acceptance failure where the existing suite passed; if the test
   rejected a valid implementation, fix it and rescore every run of that task.
4. Escalation: dropped. A B failure is a failure. Classify it.
5. Untagged 150: run as is. Record per run whether B queried or opened an untagged function.

Deviations:

- A1 tree with graph.json and policies: accepted. But grep must skip graph.json unless the path
  argument names it. Say so in A1's access paragraph.
- signatures(pkg) listing file names: accepted.
- Process-control split: accepted.

Housekeeping: add __pycache__ to .gitignore and remove the committed .pyc files.

Then run all 54 scored runs (6 tasks x 3 arms x 3 repeats). Stop only if something blocks. Report
per task and per arm, with every failure classified, and do not pool tasks into one headline
number.

## Earlier decisions

- 2026-11-11, in Experiment1.txt ("Decisions made before running"): Conduit pick rule,
  inference-first tagging, one escalation for B, checker baseline as row zero.
- 2026-11-11, review of the first push: PINS file, approx flag, `mut` tag, ambient categories,
  leaf policies, two-column row zero, hand-written task-6 ground truth.
