# Reference solutions

One reference implementation per task, each on local branch
`reference/task<N>` of the Miniflux clone, based on the plain tree `1af9501`. The diffs are saved
here as `task<N>.patch`. No experiment arm can reach them: a run sees only its own work tree
through the harness tools, which refuse `.git` paths, and no arm has a shell or network access.

They were written by six separate Claude agents given the task text, codebase hints and the
acceptance command, with the rule that a failing check they believed was wrong must be reported,
not worked around. Task 6's agent was also given the hand-written ground truth.

| Task | Files | Lines +/- | Existing suite | Acceptance (run 3 times: once by the author, twice independently) |
|---|---|---|---|---|
| 1 per-feed fetch interval | 32 | +61 / -3 | pass | 7 of 7 |
| 2 entry word count | 5 | +35 / -4 | pass | 4 of 4 |
| 3 per-user feed limit | 8 | +81 / -10 | pass | 9 of 9 |
| 4 rotate API keys | 3 | +58 / -0 | pass | 4 of 4 |
| 5 fetch timeout per feed | 8 | +31 / -7 | pass | 4 of 4 |
| 6 audit log | 8 | +91 / -20 | pass | 11 of 11, 8 of 8 paths |

Task 1 touches 32 files because 24 of them are translation files that each need one new key.

These are the "minimal correct diff" for the blast-radius metric. They are one correct design
each, not the only one.

## Test change log (ruling 3, checkpoint 2)

A test may change only when a reference shows the test is wrong, and every change is logged here.

| Date | Task | Change | Reason |
|---|---|---|---|
| 2026-11-11 | 3 | Test replaced entirely | Task replaced by ruling 1 (old task already implemented upstream). Written before the reference existed |
| | | No other changes | All six references passed their tests as first written; no author disputed a check |

## Judgment calls the references made that the task text does not settle

A run that decides these differently is not wrong, and the tests do not check them.

- Task 1: a server-requested delay (Retry-After, TTL) can still lengthen an overridden interval.
  `refresh_interval` is not accepted on feed creation. Negative values are not rejected.
- Task 2: existing entries are left null, not backfilled. The count is computed in storage on all
  three statements that write entry content.
- Task 3: the limit is enforced inside `storage.CreateFeed`, the only INSERT into feeds, so the
  web UI, Google Reader and `CreateFeedFromSubscriptionDiscovery` paths are covered too. An import
  that hits the limit keeps the feeds created before it and returns 400.
- Task 5: honoured on refresh, icon fetch and scraper; feed creation and discovery still use the
  global timeout. No UI field.
- Task 6: logging is opt-in on the storage handle and written at the write site; only the eight
  API handlers opt in. The async refresh routes and foreign-key cascades are not logged (the
  known blind spots).
