## Did the agents keep the layer accurate on their own?

No prompt asked for tag maintenance. For each of the 36 runs on the annotated tree (A1 and B) I
rebuilt the tree with the run's diff applied, re-ran the inference, and compared the tags now in
the source with what the tool infers. Script: `results/tag_upkeep.py`; data:
`results/tag-upkeep.json`.

| Task | Arm | Runs where the checker still passes | New functions tagged exactly right | New functions the tool cannot check | Existing functions whose effects changed | Tag updated exactly | Stale, minor | Stale, fails the checker |
|---|---|---|---|---|---|---|---|---|
| 1 | A1 | 3 of 3 | 2 of 2 | 0 | 0 | 0 | 0 | 0 |
| 1 | B | 3 of 3 | 1 of 1 | 0 | 0 | 0 | 0 | 0 |
| 2 | A1 | 1 of 3 | 0 of 0 | 3 | 12 | 1 | 11 | 0 |
| 2 | B | 3 of 3 | 0 of 0 | 3 | 8 | 2 | 6 | 0 |
| 3 | A1 | 3 of 3 | 8 of 8 | 0 | 9 | 7 | 2 | 0 |
| 3 | B | 3 of 3 | 6 of 6 | 0 | 9 | 9 | 0 | 0 |
| 4 | A1 | 3 of 3 | 10 of 10 | 0 | 0 | 0 | 0 | 0 |
| 4 | B | 3 of 3 | 8 of 8 | 0 | 0 | 0 | 0 | 0 |
| 5 | A1 | 2 of 3 | 1 of 1 | 1 | 0 | 0 | 0 | 0 |
| 5 | B | 3 of 3 | 2 of 2 | 0 | 0 | 0 | 0 | 0 |
| 6 | A1 | 0 of 3 | 8 of 8 | 0 | 57 | 43 | 2 | 12 |
| 6 | B | 0 of 3 | 10 of 10 | 0 | 63 | 54 | 0 | 9 |

"Stale, minor" means the tag differs only in reads, `mut`, or by declaring more than the tool
infers. "Fails the checker" means an undeclared write.

**New functions: 56 of 56 checkable ones were tagged exactly right** (29 in A1, 27 in B). Every
function an agent added got a tag, and every tag the tool could verify matched.

**Existing functions: agents updated the tags on the path they worked on and missed the callers
they never opened.**

- A1 edited 54 existing tags across 18 runs and B edited 65. Of the functions whose inferred
  effects changed, A1 left 51 of 78 exactly right and B 65 of 80.
- All 21 checker-failing stale tags are in task 6, and all are the same miss: `writes audit_log`
  not propagated upward. In every one of the six runs, the agent added a migration that creates
  the table and did not update `database.Migrate`, `cli.Parse` and `main`, which now reach that
  write. That is 18 of the 21. The other 3 are one A1 run that missed three OPML callers.
- The minor ones are mostly a missing `mut` on handlers two calls above a storage function that
  now mutates its argument (task 2).

**So the checker passes after 15 of 18 B runs and 12 of 18 A1 runs, and after 0 of 6 task-6
runs.** On the five tasks that add columns to existing tables the layer stayed consistent with
no tooling. On the one task that introduces a new table, it went stale in every run.

Three things worth separating out:

- **The stale tags are the transitive ones.** These are exactly the tags a person or agent
  cannot be expected to maintain by hand, and exactly what the tagger regenerates in six
  seconds. The result supports "regenerate on every commit", which was already in the design,
  over "agents will maintain it".
- **Three checker failures are on new functions the tool cannot certify**, where an A1 agent
  wrote `pure`. Two are a word-counting helper the tool rejects over an unresolved function
  value, where the agent is probably right. One is a method that reads `config.Opts`, where the
  agent is wrong: it reads global configuration and is not pure.
- **One agent tag was more accurate than the tool.** An A1 run on task 6 tagged
  `removeCategoryHandler` as `writes feeds`. The tool does not infer that, because the feeds are
  deleted by a foreign-key cascade. That is one of the two known blind spots, and the agent
  declared it unprompted.

Not checked: whether the agents' tags would have been right had they been wrong in the base tree.
Every agent started from tags that were already correct, so this measures upkeep, not authoring.
