# Policy files

Hand-written `.agentpolicy` files. A package uses the file in its own directory, or else the
nearest one in a parent directory (leaf inherits from parent).

## Provenance, which matters for reading row zero

- **v1, commit 1b28dec (blind).** One file per `internal/<top>` directory, written before the
  inference tool existed, from package names, the file listing and the table names in
  `internal/database/migrations.go` only.
- **v2, this commit (partly informed).** Added after Fable's review: leaf files under
  `internal/http`, `internal/reader`, `internal/ui`, and one for top-level `client/`.
  `internal/reader` itself was changed from "egress + 8 nouns" to "interior, no nouns" so the
  parent holds the common case (parsers) and the effectful leaves override it; the old reader
  noun list moved to `internal/reader/handler` unchanged.
  When v2 was written I had seen the v1 row-zero output at top-directory granularity and had traced
  `handler.RefreshFeed`, `handler.CreateFeed`, `http/server.StartWebServer` and the direct net call in
  `http/client`. I had NOT looked at inferred effects for any other leaf package, and I did not
  correct any v1 noun list using inference output (e.g. `entry_tombstones` is still missing
  everywhere outside storage, on purpose, so row zero shows it).

## Boundary semantics used by the checker

Direct = the sink call is in this package's own code.
- storage : direct SQL allowed, direct net forbidden
- egress  : direct net allowed, direct SQL forbidden
- ingress : direct SQL and direct net forbidden
- interior: direct SQL and direct net forbidden; transitive net is reported separately

`nouns` constrains transitive reads/writes: any noun a function in the package reaches must be listed
(`*` = any).
