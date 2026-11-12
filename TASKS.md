# Tasks

The text under each heading is exactly what the agent is given, in every arm. Lines marked
**Interface** were added on 2026-11-11 so that a hidden test written from the task text alone can
find the new behaviour; without them the field and route names are the agent's free choice and no
fixed test could score the result. Approved by Fable on 2026-11-11 (DECISIONS.md).

## Task 0 (shakedown, unscored)

Add `GET /v1/feeds/{feedID}/entries/count` to the API. It returns `{"count": N}`, where N is the
number of entries in that feed. A feed that does not exist, or that belongs to another user,
returns 404.

## Task 1: per-feed fetch interval

Add an optional per-feed polling interval that overrides the global one. A migration adds the
column, the field is exposed in the API and in the web UI, and the scheduler respects it.

**Interface:** the field is an integer number of minutes named `refresh_interval`; 0 means "use
the global interval". It appears in the API feed object, is accepted by `PUT /v1/feeds/{feedID}`,
and the feed edit form in the web UI has an input named `refresh_interval`.

## Task 2: entry word count

Compute and store a word count when an entry is saved, and expose it in the API. Entries that
already exist are either backfilled or left null; new entries are always populated.

**Interface:** the API entry object has an integer field `word_count` (null where unknown). Words
are counted on the entry content with HTML tags removed.

## Task 3: per-user feed limit

Add a per-user limit on the number of feeds.

**Interface:** the user object has an integer field `max_feeds`; 0 means unlimited. Only an
administrator can change it, with `PUT /v1/users/{userID}`. Once a user has `max_feeds` feeds, no
request may create another one for that user: `POST /v1/feeds` returns a 4xx status and creates
nothing, and `POST /v1/import` never leaves the user with more than `max_feeds` feeds.

(Replaces "block rule by author", which Miniflux already implements. Wording from Fable's ruling
on checkpoint 2.)

## Task 4: rotate API keys

Add an endpoint to regenerate a user's API key and invalidate the old one. The old key fails
immediately and the new key works.

**Interface:** `POST /v1/api-keys/{apiKeyID}/regenerate` returns the API key object with its new
`token`.

## Task 5: fetch timeout per feed

Allow a per-feed HTTP timeout that overrides the global one. A slow server triggers the timeout at
the per-feed value, not the global one.

**Interface:** the field is an integer number of seconds named `fetch_timeout`; 0 means "use the
global timeout". It appears in the API feed object and is accepted by `PUT /v1/feeds/{feedID}`.

## Task 6: audit log for writes

Every API request that modifies a row in users or feeds must append a row to audit_log. The only
exception is the last-login timestamp updated during authentication.

(Wording from Fable's ruling 5. No interface line: the test only counts rows in `audit_log`.)
