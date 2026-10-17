---
description: 'Full-text search across memory observations with a structured-index primary path and a substring fallback when the index cannot answer.'
visibility: 'public'
---

# Observation Full-Text Search — Spec

## What it is

Memory observations are retrievable by free-text query. The search path always tries the structured full-text index first; when the index cannot answer (malformed query, empty query, missing index module, etc.) the path falls through to a substring search against the live text fields. Both branches apply the same optional filters (project, observation type, identity scope) and return results ordered newest-first within a caller-supplied limit. Callers reach this surface via `telec memories search`, via the memory service's programmatic search entry, or — for "list" semantics — by passing an empty query (see `observation-recent-list`).

Only current memories are returned: a retired memory or a business prospect is never a result of this surface (`local/projects/teleclaude/spec/feature/memory/memory-curation` UC-MC3).

## Canonical fields

### Use cases

#### Search memories for a phrase

```gherkin
Given a human operator wants to find stored memories matching a phrase
And may narrow the results by type or project
When they search for that phrase with an optional result limit
Then matching current observations are shown newest first within the limit
And an empty result is reported clearly
```

### Cross-context references

- `identity` — supplies the identity scope used for inclusion-of-unscoped filtering; see `docs/local/spec/domain/identity.md` and `identity-key-ownership`.

## Known caveats

- **Empty query falls through to substring search.** The structured-index path rejects empty queries; the fallback then matches every live observation and behaves as a recent-list query (see `observation-recent-list`).
- **Failures of the primary path are silent at the log level.** The fallback path debug-logs the query but does not surface the failure to the caller; results may come from either branch with no signal in the response. Whether to keep the silent fallback is a memory-domain decision.
- **The CLI does not expose an identity-scope option.** Identity-scoped filtering is reachable only programmatically (see `memory-context-injection`).
- **No snippet excerpts.** The response carries the full observation body; query-centered excerpts described by the memory domain spec are not produced here. CLI rendering truncates long fields for display; the truncation is presentational only.
- **No author filter.** Authoring identity is recorded via the looser identity-scope mechanism (see `identity-key-ownership`); no separate author-principal filter exists on this surface.
- **Limit ceiling.** The search surface enforces an upper bound on the requested limit (1–100); callers cannot exceed it without going through the underlying programmatic search entry.
