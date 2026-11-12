# Task 6 ground truth: API write paths to `users` and `feeds`

Written by hand on 2026-11-11 from the Miniflux source at `1af9501`, using grep and reading
only. `graph.json` was not consulted to build this list. (I had already seen graph output for
other purposes, so this is "derived independently", not "derived blind"; the comparison against
graph.json at the bottom was run only after the list was fixed.)

Method:
1. Grep `internal/` (minus migrations and tests) for every `INSERT INTO`, `UPDATE`, `DELETE FROM`
   on `users` or `feeds`, including statements with the table name on the following line.
   All hits are in `internal/storage`.
2. Grep every call site of those storage functions.
3. Read `internal/api/api.go` for the route table and each handler on the path.

## Storage functions that write `users` or `feeds`

| Storage function | Statement | Table |
|---|---|---|
| `CreateUser` (user.go:63) | INSERT | users |
| `UpdateUser` (user.go:180, two branches) | UPDATE | users |
| `RemoveUser` (user.go:585) | DELETE | users |
| `SetLastLogin` (user.go:33) | UPDATE | users, **excluded by decision** |
| `CreateFeed` (feed.go:246) | INSERT | feeds |
| `UpdateFeed` (feed.go:363) | UPDATE | feeds |
| `UpdateFeedError` (feed.go:464) | UPDATE | feeds |
| `RemoveFeed` (feed.go:491) | DELETE | feeds |
| `RemoveAndReplaceCategoriesByName` (category.go:289) | UPDATE | feeds, not reachable from `internal/api` (Google Reader API only) |
| `ResetFeedErrors`, `ResetNextCheckAt` (feed.go:500, 507) | UPDATE | feeds, CLI only |

## API write paths that must produce an audit row (8 routes)

| # | Route | Handler | Path to the write | Table |
|---|---|---|---|---|
| 1 | `POST /v1/users` | `createUserHandler` | `store.CreateUser` (user_handlers.go:49) | users |
| 2 | `PUT /v1/users/{userID}` | `updateUserHandler` | `store.UpdateUser` (user_handlers.go:100) | users |
| 3 | `DELETE /v1/users/{userID}` | `removeUserHandler` | `store.RemoveUser` (user_handlers.go:269) | users |
| 4 | `POST /v1/feeds` | `createFeedHandler` | `handler.CreateFeed` -> `store.CreateFeed` (reader/handler/handler.go:190) | feeds |
| 5 | `PUT /v1/feeds/{feedID}` | `updateFeedHandler` | `store.UpdateFeed` (feed_handlers.go:152) | feeds |
| 6 | `DELETE /v1/feeds/{feedID}` | `removeFeedHandler` | `store.RemoveFeed` (feed_handlers.go:281) | feeds |
| 7 | `PUT /v1/feeds/{feedID}/refresh` | `refreshFeedHandler` | `handler.RefreshFeed` -> `store.UpdateFeed` (handler.go:378) or, on failure, `store.UpdateFeedError` (handler.go:36) | feeds |
| 8 | `POST /v1/import` | `importFeedsHandler` | `opml.Handler.Import` -> `store.CreateFeed` (reader/opml/handler.go:91), once per imported feed | feeds |

Eight synchronous write paths. A correct solution audits all eight. Path 7 is the one most
likely to be missed: the route name says "refresh", the write is two packages away, and it has
two different writers depending on success or failure. Path 8 writes many rows per request.

Whether path 7 "counts" is a specification question for Fable: a refresh updates bookkeeping
columns on `feeds` (checked_at, etag, error count), not user-authored data. The task text says
"every write to users or feeds through the API", so I have listed it. If it is excluded, say so in
the task wording, because an agent that audits it would otherwise be marked as over-reaching.

## Excluded by decision

- `SetLastLogin`, called from the API auth middleware on every authenticated request
  (api/middleware.go:78 and :173). It is a write to `users` through the API, and the effect
  tags do expose it; it is excluded because auditing every request is not the intent.

## Known blind spots (not expected from either condition, do not score as misses)

- **Async refresh through the worker pool.** `PUT /v1/feeds/refresh` (`refreshAllFeedsHandler`,
  feed_handlers.go:115) and `PUT /v1/categories/{categoryID}/refresh` (`refreshCategoryHandler`,
  category_handlers.go:196) run `go h.pool.Push(jobs)`. The handler returns immediately; the
  `feeds` writes happen later in `worker.Run` -> `handler.RefreshFeed` on another goroutine, with
  no request context. Neither the handler's tag nor its callees show `writes feeds`.
- **Foreign-key cascades.** `DELETE /v1/users/{userID}` cascades to that user's `feeds` rows
  (migrations.go:70, `user_id ... on delete cascade`), and `DELETE /v1/categories/{categoryID}`
  (`removeCategoryHandler` -> `store.RemoveCategory`) cascades to `feeds` through
  `category_id references categories(id) on delete cascade` (migrations.go:71). No Go code
  issues those deletes, so no static tag can show them.
- The same writers are reachable from the web UI (`internal/ui`), the Google Reader API and the
  CLI. Those are out of scope: the task says "through the API".
