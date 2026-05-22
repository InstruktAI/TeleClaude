---
id: 'project/spec/feature/memory/observation-bulk-fetch'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Bulk-fetch observations by a list of integer ids — an HTTP-only convenience over SELECT IN.'
---

# Observation Bulk Fetch — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/memory.md

## What it is

`POST /api/memory/batch` accepts a list of observation ids and an optional project filter and returns the matching observations in a single response, ordered by `created_at_epoch DESC`. The endpoint serves callers that already hold a set of ids (e.g., from a prior search) and want the full payload for each without making N individual round-trips. The implementation issues one `SELECT ... WHERE id IN (...)` and converts rows through the shared `_row_to_search_result` helper.

## Canonical fields

### Use cases

#### Batch fetch

```
Given an HTTP caller sends `POST /api/memory/batch` with body `{"ids": [<int>, ...], "project": <slug>}` (project optional)
When the daemon's `batch_fetch` handler runs
Then it calls `MemorySearch.batch_fetch(ids, project)`
And `MemorySearch.batch_fetch` issues `SELECT ... FROM memory_observations WHERE id IN (:id_0, :id_1, ...)` with optional `AND project = :project`
And orders the result by `created_at_epoch DESC`
And returns the matching rows as a JSON array of `SearchResult` dicts
```

#### Empty input

```
Given the request body has `ids: []`
When `MemorySearch.batch_fetch` runs
Then it short-circuits and returns `[]` without issuing any SQL
And the HTTP response is `200 []`
```

#### Mixed-found ids

```
Given the request supplies ids `[a, b, c]` where only `a` and `c` exist
When the SQL executes
Then the response contains only the rows for `a` and `c`
And the response order is `created_at_epoch DESC` regardless of input order
And there is no per-id error reporting
```

### Implementation pointers (v1)

- `MemorySearch.batch_fetch` — `teleclaude/memory/search.py:199`
- HTTP entry — `teleclaude/memory/api_routes.py:97` (`POST /api/memory/batch`)
- Request schema — `teleclaude/memory/api_routes.py:42` (`BatchRequest`)
- Row conversion — `teleclaude/memory/search.py:19` (`_row_to_search_result`)

### Cross-context references

- None. Batch fetch is contained within the `memory` context.

## Known caveats

- **HTTP-only surface — no production caller.** There is no `telec memories batch` verb, and no internal Python code calls `MemorySearch.batch_fetch` outside of the HTTP route. The endpoint is reachable but unexercised by the codebase. v2 design must decide whether to keep, redesign (e.g., as a query parameter on `/search`), or drop this surface.
- **No identity_key filter.** Unlike `/search`, `/batch` ignores identity scope entirely. Any caller with a valid id can fetch any observation regardless of how it was tagged at save.
- **No type filter.** Type-based progressive disclosure is not available on this surface.
- **No `limit`.** Every supplied id is queried; the response size is bounded only by the input length. Callers concerned about response size must trim their id list before posting.
- **Missing ids are silent.** There is no "not found" indication per-id; callers diff the input list against returned ids themselves.
- **Empty `ids: []` is a no-op.** The empty-list short-circuit means callers receive `200 []` without exercising the SQL path.
