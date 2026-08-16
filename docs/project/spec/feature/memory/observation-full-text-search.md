---
description: 'Full-text search across memory observations with a structured-index primary path and a substring fallback when the index cannot answer.'
visibility: 'public'
---

# Observation Full-Text Search — Spec

## What it is

Memory observations are retrievable by free-text query. The search path always tries the structured full-text index first; when the index cannot answer (malformed query, empty query, missing index module, etc.) the path falls through to a substring search against the live text fields. Both branches apply the same optional filters (project, observation type, identity scope) and return results ordered newest-first within a caller-supplied limit. Callers reach this surface via `telec memories search`, via the memory service's programmatic search entry, or — for "list" semantics — by passing an empty query (see `observation-recent-list`).

## Canonical fields

### Use cases

#### Search via CLI

```
Given a human or agent runs `telec memories search "<query>" [--limit N] [--type <obs_type>] [--project <slug>]`
When the CLI builds the request
Then it joins the positional arguments into a single space-separated query string
And asks the memory service to search with that query, the limit (default 20), and any supplied filters
And renders the returned rows in the standard observation table (or prints "No memories found for '<query>'" when the response is empty)
```

#### Primary structured-index path

```
Given the memory service receives a non-empty query
When it issues its search
Then it consults the structured full-text index first
And returns the matching observations ordered newest-first, bounded by the requested limit
```

#### Substring fallback

```
Given the structured-index attempt raises any error (malformed query, empty query, missing index module)
When the search path catches the error
Then it logs a debug-level message naming the query
And falls through to a substring search over the live observation text fields
And applies the same optional project, type, and identity-scope filters as the primary branch
And returns the matching observations ordered newest-first, bounded by the requested limit
```

#### Project filter

```
Given the caller supplies a project slug
When either search branch builds its result set
Then only observations belonging to that project appear in the response
```

#### Type filter for progressive disclosure

```
Given the caller supplies an observation type (one of the values defined in `observation-type-taxonomy`)
When either search branch builds its result set
Then only observations whose type matches appear in the response
```

#### Identity-scoped search

```
Given the caller supplies an identity scope (programmatic callers only)
When either search branch builds its result set
Then the response contains observations tagged with that scope PLUS observations with no scope
And observations tagged with any other scope are excluded
```

### Cross-context references

- `identity` — supplies the identity scope used for inclusion-of-unscoped filtering; see `docs/project/spec/domain/identity.md` and `identity-key-ownership`.

## Known caveats

- **Empty query falls through to substring search.** The structured-index path rejects empty queries; the fallback then matches every live observation and behaves as a recent-list query (see `observation-recent-list`).
- **Failures of the primary path are silent at the log level.** The fallback path debug-logs the query but does not surface the failure to the caller; results may come from either branch with no signal in the response. Whether to keep the silent fallback is a memory-domain decision.
- **The CLI does not expose an identity-scope option.** Identity-scoped filtering is reachable only programmatically (see `memory-context-injection`).
- **No snippet excerpts.** The response carries the full observation body; query-centered excerpts described by the memory domain spec are not produced here. CLI rendering truncates long fields for display; the truncation is presentational only.
- **No author filter.** Authoring identity is recorded via the looser identity-scope mechanism (see `identity-key-ownership`); no separate author-principal filter exists on this surface.
- **Limit ceiling.** The search surface enforces an upper bound on the requested limit (1–100); callers cannot exceed it without going through the underlying programmatic search entry.
