---
id: 'project/spec/feature/memory/observation-full-text-search'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'internal'
applies_to: 'v1'
status: 'actual'
description: 'Full-text search across memory observations with FTS5 as the primary index and a LIKE fallback when FTS5 cannot answer.'
---

# Observation Full-Text Search — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/memory.md

## What it is

Memory observations are retrievable by free-text query against the `memory_observations_fts` virtual table. The search path always tries FTS5 first; when FTS5 raises (malformed query, empty query, missing module, etc.) the path falls through to a SQL `LIKE` query against the live text fields. Both branches apply the same optional filters (`project`, `type`, `identity_key`) and return rows ordered by `created_at_epoch DESC` with a caller-supplied limit. Callers reach this surface via `telec memories search`, `GET /api/memory/search`, or — for "list" semantics — by passing an empty query (see `observation-recent-list`).

## Canonical fields

### Use cases

#### Search via CLI

```
Given a human or agent runs `telec memories search "<query>" [--limit N] [--type <obs_type>] [--project <slug>]`
When the CLI builds the request
Then it joins the positional arguments into a single space-separated `query` string
And calls `GET /api/memory/search` with `query`, `limit` (default 20), and any supplied filters
And renders the returned rows in the standard observation table (or prints "No memories found for '<query>'" when the response is empty)
```

#### FTS5 primary path

```
Given the search endpoint receives a non-empty `query`
When `MemorySearch.search` opens its FTS5 attempt
Then it executes `SELECT ... FROM memory_observations WHERE id IN (SELECT rowid FROM memory_observations_fts WHERE memory_observations_fts MATCH :query)` with any supplied filters appended
And the SQL is ordered by `created_at_epoch DESC` and bounded by `limit`
And on success the matching rows are converted to `SearchResult` and returned
```

#### LIKE fallback

```
Given the FTS5 attempt raises any exception (malformed FTS5 query, empty query, missing FTS5 extension)
When the search path catches the exception
Then it logs a debug-level message naming the query
And executes a LIKE-pattern query over the live observation text fields with `pattern = "%" + query + "%"`
And applies the same optional `project`, `type`, and `identity_key` filters as the FTS5 branch
And returns the matching rows ordered by `created_at_epoch DESC` bounded by `limit`
```

#### Project filter

```
Given the caller supplies `project=<slug>`
When either search branch builds its SQL
Then `AND project = :project` is appended to the WHERE clause
And only rows for that project appear in the response
```

#### Type filter for progressive disclosure

```
Given the caller supplies `type=<obs_type>` (one of the v1 observation-type values; see `observation-type-taxonomy`)
When either search branch builds its SQL
Then `AND type = :obs_type` is appended to the WHERE clause
And only rows whose `type` column matches appear in the response
```

#### Identity-scoped search

```
Given the caller supplies `identity_key=<key>` (HTTP only)
When either search branch builds its SQL
Then `AND (identity_key IS NULL OR identity_key = :identity_key)` is appended to the WHERE clause
And the response contains observations tagged with that identity PLUS observations with no identity scope
And observations tagged with any other identity are excluded
```

### Implementation pointers (v1)

- `MemorySearch.search` (async, primary surface) — `teleclaude/memory/search.py:61`
- FTS5 attempt — `teleclaude/memory/search.py:82`
- LIKE fallback — `teleclaude/memory/search.py:107`
- Shared column projection — `teleclaude/memory/search.py:55` (`_SEARCH_COLUMNS`)
- Row → `SearchResult` conversion — `teleclaude/memory/search.py:19` (`_row_to_search_result`)
- HTTP entry — `teleclaude/memory/api_routes.py:68` (`GET /api/memory/search`)
- CLI entry — `teleclaude/cli/telec/handlers/memories.py:337` (`_handle_memories_search`)
- CLI → API transport — `teleclaude/cli/api_client.py:792` (`memory_search`)
- FTS5 virtual table + triggers — `teleclaude/core/migrations/001_initial_schema.py:332`

### Cross-context references

- `identity` — supplies the `identity_key` used for inclusion-of-unscoped filtering; see `docs/project/spec/domain/identity.md` and `identity-key-ownership`.

## Known caveats

- **Empty query falls through to LIKE.** FTS5 raises on `MATCH ''`. The fallback constructs `LIKE '%%'`, which matches every non-NULL `narrative` and effectively becomes a recent-list query (see `observation-recent-list`).
- **FTS5 failures are silent at the log level.** The fallback path debug-logs the query but does not surface the failure to the caller; results may come from either branch with no signal in the response. v2 designers should decide whether this is acceptable.
- **The CLI does NOT expose `--identity-key`.** Identity-scoped filtering is reachable only through HTTP and through the in-process `generate_context_sync` path consumed by the hook receiver (see `memory-context-injection`).
- **No snippet excerpts.** The response carries full `narrative`; the v2 domain spec describes snippet excerpts (query-centered) for UC-MEM-2, but v1 returns the entire body. CLI rendering truncates to 60 chars for display; the truncation is presentational only.
- **Author filter does not exist in v1.** The v2 domain spec's UC-MEM-2 includes `--author <principal>`; v1 has no author column and no author filter. The `identity_key` filter is the nearest analog.
- **Server-side `limit` ceiling.** The HTTP endpoint enforces `1 ≤ limit ≤ 100`. Callers cannot bypass this without going through the underlying `MemorySearch.search` Python API.
