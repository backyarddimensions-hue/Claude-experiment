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

## Earlier decisions

- 2026-11-11, in Experiment1.txt ("Decisions made before running"): Conduit pick rule,
  inference-first tagging, one escalation for B, checker baseline as row zero.
- 2026-11-11, review of the first push: PINS file, approx flag, `mut` tag, ambient categories,
  leaf policies, two-column row zero, hand-written task-6 ground truth.
