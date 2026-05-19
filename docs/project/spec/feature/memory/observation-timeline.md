---
id: 'project/spec/feature/memory/observation-timeline'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'internal'
applies_to: 'v1'
status: 'actual'
description: 'Retrieve a chronological window of observations around an anchor observation id.'
---

# Observation Timeline — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/memory.md

## What it is

The timeline surface returns observations chronologically arranged around a single anchor observation. Given an anchor `id`, the path looks up the anchor's `created_at_epoch`, fetches up to `depth_before` observations saved at-or-before that epoch, includes the anchor row itself, and fetches up to `depth_after` observations saved at-or-after. The before and after windows are optionally bounded by a project filter; the anchor lookup and anchor row are not project-scoped. The use case is "what was happening around this moment in the project's memory" — the anchor is supplied by the caller from a prior list or search.

## Canonical fields

### Use cases

#### Timeline via CLI

```
Given a human or agent runs `telec memories timeline <id> [--before N] [--after N] [--project <slug>]`
And `--before` defaults to 3, `--after` defaults to 3
When the CLI builds the request
Then it calls `GET /api/memory/timeline` with `anchor=<id>`, `depth_before`, `depth_after`, and optionally `project`
And renders the returned rows in the standard observation table marking the anchor row with the suffix " ◀"
And prints "No observations found around #<id>" when the response is empty
```

#### Anchor lookup

```
Given the timeline endpoint receives `anchor=<id>`
When `MemorySearch.timeline` opens
Then it queries `SELECT created_at_epoch FROM memory_observations WHERE id = :id`
And reads the anchor's epoch from the result
And if no row matches, returns an empty list (HTTP 200 with `[]`)
```

#### Before window

```
Given the anchor's epoch is known
And `depth_before > 0`
When the before window query runs
Then it executes `WHERE created_at_epoch <= :epoch AND id != :id` (optionally `AND project = :project`)
And orders the result by `created_at_epoch DESC` limited to `depth_before`
And reverses the result so the oldest of the window appears first
```

#### Anchor row

```
Given the anchor exists
When the timeline path queries for the anchor row
Then it executes `SELECT ... FROM memory_observations WHERE id = :id`
And places the anchor row between the before and after windows in the returned list
```

#### After window

```
Given the anchor's epoch is known
And `depth_after > 0`
When the after window query runs
Then it executes `WHERE created_at_epoch >= :epoch AND id != :id` (optionally `AND project = :project`)
And orders the result by `created_at_epoch ASC` limited to `depth_after`
```

#### Merged response

```
Given the before, anchor, and after sub-queries have all returned
When the timeline path composes the response
Then it concatenates `before_rows + [anchor_row] + after_rows` in that order
And each row is converted to `SearchResult` via the shared row converter
And the merged list is returned to the caller
```

### Implementation pointers (v1)

- `MemorySearch.timeline` — `teleclaude/memory/search.py:129`
- Anchor lookup — `teleclaude/memory/search.py:138`
- Before-window SQL — `teleclaude/memory/search.py:149`
- Anchor row SQL — `teleclaude/memory/search.py:168`
- After-window SQL — `teleclaude/memory/search.py:177`
- HTTP entry — `teleclaude/memory/api_routes.py:84` (`GET /api/memory/timeline`)
- CLI entry — `teleclaude/cli/telec/handlers/memories.py:388` (`_handle_memories_timeline`)
- CLI → API transport — `teleclaude/cli/api_client.py:849` (`memory_timeline`)
- CLI anchor marker rendering — `teleclaude/cli/telec/handlers/memories.py:122`

### Cross-context references

- None. Timeline is contained within the `memory` context.

## Known caveats

- **Anchor is supplied by id, not stored as a relationship.** v1's `MemoryObservation` schema has no `anchor_id` column. The "anchor" is purely a query parameter; observations are not linked to anchors in storage. v2's domain spec describes a stored `anchor_id` aggregate field — v1 has no equivalent.
- **`<=` and `>=` overlap on the anchor's epoch.** Both the before and after queries include rows at the exact anchor epoch (other than the anchor itself, filtered via `id != :id`). When several observations share the same epoch, those neighbors can appear in BOTH the before and after windows, producing duplicates. The dedup discipline is the caller's job.
- **Server-side depth ceiling.** The HTTP endpoint enforces `0 ≤ depth_before ≤ 20` and `0 ≤ depth_after ≤ 20`. Callers cannot bypass this without going through `MemorySearch.timeline` directly.
- **No identity_key filter on timeline.** Unlike search, the timeline path does NOT scope by identity. Timeline always returns all observations in the window (subject only to project filter).
- **Project filter does not constrain the anchor.** The optional project filter applies to the before and after window queries only. The anchor epoch lookup and anchor row query use `id` alone, so an anchor from another project can still appear in the response while neighboring rows are project-filtered.
- **Anchor row appears even with `depth_before=0, depth_after=0`.** The anchor row query runs unconditionally.
- **No type filter on timeline.** Unlike search, timeline cannot be narrowed by observation type.
