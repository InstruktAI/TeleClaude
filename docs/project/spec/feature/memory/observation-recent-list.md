---
id: 'project/spec/feature/memory/observation-recent-list'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'List the most recent observations — implemented as an empty-query search that leans on the LIKE fallback.'
---

# Observation Recent List — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/memory.md

## What it is

`telec memories list` returns the N most recent observations for the caller, optionally filtered by `--type` and `--project`. There is no dedicated `list` endpoint on the HTTP API; the CLI implements list by issuing an empty-query search (`GET /api/memory/search?query=`). The search path's FTS5 attempt rejects the empty query, the LIKE-pattern fallback constructs `%%` which matches every non-NULL text column, and the rows are returned ordered by `created_at_epoch DESC` with the requested limit. The quirk is intentional: it gives "list" semantics without a second SQL surface.

## Canonical fields

### Use cases

#### List most recent

```
Given a human or agent runs `telec memories list [--limit N] [--type <obs_type>] [--project <slug>]`
And `--limit` defaults to 50, `--type` and `--project` default to absent
When the CLI builds the request
Then it calls the same search transport as `telec memories search` with an empty query string
And forwards `limit`, `type`, and `project` as supplied
And renders the returned rows in the standard observation table (or prints "No memories found." when the response is empty)
```

#### Empty-query semantics on the server

```
Given the search endpoint receives `query=""`
When `MemorySearch.search` runs its FTS5 attempt
Then `memory_observations_fts MATCH ''` raises an exception
And the search falls through to its LIKE-pattern branch
And the LIKE branch constructs the pattern `%%` (literal percent on both sides of the empty query)
And executes a LIKE query over live observation text fields with optional `project` and `type` filters
And returns the matching rows ordered by `created_at_epoch DESC` limited to the requested `limit`
```

#### Type filter

```
Given the caller supplies `--type <obs_type>`
When the search request is built
Then the request includes `type=<obs_type>`
And the server appends `AND type = :obs_type` to the SQL
And the response contains only rows whose `type` column equals the requested value
```

#### Project filter

```
Given the caller supplies `--project <slug>`
When the search request is built
Then the request includes `project=<slug>`
And the server appends `AND project = :project` to the SQL
And the response contains only rows whose `project` column equals the requested value
```

### Implementation pointers (v1)

- CLI parsing — `teleclaude/cli/telec/handlers/memories.py:135` (`_parse_memories_list_args`)
- CLI handler — `teleclaude/cli/telec/handlers/memories.py:317` (`_handle_memories_list`) — calls `_memory_search("", limit, obs_type, project)`
- CLI → API transport — `teleclaude/cli/api_client.py:792` (`memory_search`)
- HTTP entry — `teleclaude/memory/api_routes.py:68` (`GET /api/memory/search`)
- Server-side empty-query fallback — `teleclaude/memory/search.py:82` (FTS5 attempt) and `teleclaude/memory/search.py:107` (LIKE fallback)

### Cross-context references

- None. List is fully contained within the `memory` context's search surface.

## Known caveats

- **There is no dedicated `/api/memory/list` route.** List is a CLI-only verb that piggy-backs on `GET /api/memory/search` with an empty query. HTTP callers wanting "list" semantics must call `/api/memory/search?query=`.
- **The `%%` LIKE pattern matches every row with a non-null `narrative`.** Since `narrative` is always populated on save (see `observation-save`), the pattern never excludes a live row. Rows with `narrative IS NULL` would be skipped, but no production save path produces them.
- **`--limit` default is 50 at the CLI; the HTTP `/search` endpoint defaults `limit` to 20 with a hard ceiling of 100.** The CLI's 50 is below the ceiling, so the value flows through unmodified.
- **`identity_key` filtering is NOT applied for CLI list.** The CLI does not forward `identity_key`; results include observations from every identity scope (including unscoped). HTTP callers that supply `identity_key` to `/search` get the inclusion-of-unscoped semantics described in `identity-key-ownership`.
- **Type validation lives in the CLI.** Invalid `--type` values are rejected with a usage error before any HTTP request fires. The HTTP endpoint uses FastAPI's enum coercion for the same set.
