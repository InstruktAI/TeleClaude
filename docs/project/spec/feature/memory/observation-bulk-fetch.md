---
description: 'Bulk-fetch observations by id list — a single-call convenience over per-id fetch, ordered newest-first.'
visibility: 'public'
---

# Observation Bulk Fetch — Spec

## What it is

The bulk-fetch surface accepts a list of observation ids and an optional project filter and returns the matching observations in a single response, ordered newest-first. It serves callers that already hold a set of ids (for example, from a prior search) and want the full payload for each without issuing one request per id.

## Canonical fields

### Use cases

#### Batch fetch

```
Given a caller supplies a non-empty list of observation ids (optionally with a project filter)
When the memory service handles the request
Then it returns the observations whose ids appear in the input list (and that match the optional project filter)
And the result is ordered newest-first
```

#### Empty input

```
Given the caller supplies an empty id list
When the memory service handles the request
Then no observations are read and the response is an empty list
```

#### Mixed-found ids

```
Given the caller supplies ids [a, b, c] where only a and c exist
When the memory service handles the request
Then the response contains the observations for a and c only
And the response order is newest-first regardless of input order
And there is no per-id error reporting; missing ids are simply absent from the result
```

### Cross-context references

- None. Bulk fetch is contained within the `memory` context.

## Known caveats

- **No production caller.** No internal code consumes bulk-fetch today; it is reachable but unexercised. Whether to keep, redesign (for example, as a parameter on search), or drop the surface is a memory-domain decision.
- **No identity scope filter.** Bulk-fetch ignores identity scope entirely. Any caller with a valid id can fetch the matching observation regardless of how it was tagged at save (see `identity-key-ownership`).
- **No type filter.** Type-based progressive disclosure is not available on this surface.
- **No limit.** Every supplied id is queried; response size is bounded only by the input length. Callers concerned about response size must trim their id list before submitting.
- **Missing ids are silent.** There is no "not found" indication per-id; callers diff the input list against returned ids themselves.
