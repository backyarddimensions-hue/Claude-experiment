# Policy files

Hand-written `.agentpolicy` files, one per top-level package directory.
The Miniflux set was written on 2026-11-11 BEFORE the inference tool existed, from package
names, the file listing and the table names in `internal/database/migrations.go` only.
This ordering is what makes "row zero" meaningful: the checker compares inferred effects
against a declaration that was not derived from the inference.

Boundary semantics used by the checker (direct = the sink call is in this package's own code):
- storage : direct SQL allowed, direct net forbidden
- egress  : direct net allowed, direct SQL forbidden
- ingress : direct SQL and direct net forbidden
- interior: direct SQL and direct net forbidden
`nouns` constrains transitive reads/writes: any noun a function in the package reaches must be listed.
