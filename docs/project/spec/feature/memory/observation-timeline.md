---
description: 'Retrieve a chronological window of observations around an anchor observation.'
visibility: 'public'
---

# Observation Timeline — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/memory.md

## What it is

The timeline surface returns observations chronologically arranged around a single anchor observation. Given an anchor id, the path looks up the anchor's creation timestamp, fetches up to `depth_before` observations created at-or-before that timestamp, includes the anchor itself, and fetches up to `depth_after` observations created at-or-after. The before and after windows may be bounded by a project filter; the anchor lookup and anchor row itself are not project-scoped. The use case is "what was happening around this moment in the project's memory" — the anchor is supplied by the caller from a prior list or search result.

## Canonical fields

### Use cases

#### Timeline via CLI

```
Given a human or agent runs `telec memories timeline <id> [--before N] [--after N] [--project <slug>]`
And `--before` defaults to 3, `--after` defaults to 3
When the CLI builds the request
Then it asks the memory service for the timeline window around the anchor with the supplied depths and optional project filter
And renders the returned rows in the standard observation table marking the anchor row with the suffix " ◀"
And prints "No observations found around #<id>" when the response is empty
```

#### Anchor lookup

```
Given the memory service receives a timeline request for an anchor id
When it builds the response
Then it first looks up the anchor's creation timestamp
And if no observation matches that id, the response is an empty list
```

#### Before window

```
Given the anchor's creation timestamp is known
And depth_before > 0
When the memory service computes the before window
Then it returns up to depth_before observations created at-or-before the anchor's timestamp (excluding the anchor itself)
And the before window is optionally narrowed by the project filter
And the before window is ordered so the oldest entry appears first in the merged response
```

#### Anchor row

```
Given the anchor exists
When the memory service composes the response
Then it includes the anchor observation between the before and after windows
```

#### After window

```
Given the anchor's creation timestamp is known
And depth_after > 0
When the memory service computes the after window
Then it returns up to depth_after observations created at-or-after the anchor's timestamp (excluding the anchor itself)
And the after window is optionally narrowed by the project filter
And the after window is ordered oldest-first
```

#### Merged response

```
Given the before window, anchor, and after window are all resolved
When the memory service composes the response
Then it concatenates `before + [anchor] + after` in that order
And returns the merged list to the caller
```

### Cross-context references

- None. Timeline is contained within the `memory` context.

## Known caveats

- **Anchor is a query parameter, not a stored relationship.** Observations are not linked to anchors in storage. The memory domain spec describes a stored anchor field — promoting the anchor to a first-class field is a cutover decision.
- **Boundary overlap on the anchor's timestamp.** Both the before and after windows include observations at the exact anchor timestamp (other than the anchor itself, which is excluded). When several observations share the same timestamp, those neighbors can appear in BOTH windows, producing duplicates. Dedup is the caller's job.
- **Depth ceiling.** The timeline surface enforces an upper bound on each depth (0–20). Callers cannot exceed it without going through the underlying programmatic timeline entry.
- **No identity-scope filter.** Unlike search, timeline does NOT filter by identity scope. It always returns all observations in the window (subject only to the project filter).
- **Project filter does not constrain the anchor.** The optional project filter applies to the before and after window queries only. The anchor lookup uses the id alone, so an anchor from another project can appear in the response while neighboring rows are project-filtered.
- **Anchor row appears even with depth_before=0, depth_after=0.** The anchor is included unconditionally.
- **No type filter on timeline.** Unlike search, timeline cannot be narrowed by observation type.
