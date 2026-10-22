---
description: 'Retrieve a chronological window of observations around an anchor observation.'
visibility: 'public'
---

# Observation Timeline — Spec

## What it is

The timeline surface returns observations chronologically arranged around a single anchor observation. Given an anchor id, the path looks up the anchor's creation timestamp, fetches up to `depth_before` observations created at-or-before that timestamp, includes the anchor itself, and fetches up to `depth_after` observations created at-or-after. The before and after windows may be bounded by a project filter; the anchor lookup and anchor row itself are not project-scoped. The use case is "what was happening around this moment in the project's memory" — the anchor is supplied by the caller from a prior list or search result.

Only current memories are returned: a retired memory or a business prospect is never a result of this surface (`local/projects/teleclaude/spec/feature/memory/memory-curation` UC-MC3).

The CLI defaults to three observations before and after the anchor.

## Canonical fields

### Use cases

#### An operator reviews observations around a chosen memory

```
Given an operator has an observation from a prior memory search or list
When the operator requests its timeline
Then the CLI shows observations in chronological context around the anchor
And marks the anchor in the results
And reports when no observation resolves as the anchor
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
