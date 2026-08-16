---
description: 'List the most recent observations — implemented as an empty-query search that resolves through the substring fallback.'
visibility: 'public'
---

# Observation Recent List — Spec

## What it is

`telec memories list` returns the N most recent observations for the caller, optionally narrowed by observation type or project. There is no dedicated list verb on the memory service; the CLI implements list by asking the search surface with an empty query string. The search path's primary structured-index attempt rejects the empty query, the substring fallback then matches every live observation, and the response is returned ordered newest-first within the requested limit. The quirk is intentional: it gives "list" semantics without a second backend surface.

## Canonical fields

### Use cases

#### List most recent

```
Given a human or agent runs `telec memories list [--limit N] [--type <obs_type>] [--project <slug>]`
And `--limit` defaults to 50, `--type` and `--project` default to absent
When the CLI builds the request
Then it calls the memory search surface with an empty query string
And forwards limit, type, and project as supplied
And renders the returned rows in the standard observation table (or prints "No memories found." when the response is empty)
```

#### Empty-query semantics

```
Given the memory search surface receives an empty query
When it issues its search
Then the primary structured-index attempt rejects the empty query
And the substring fallback matches every live observation
And the response honors the optional project and type filters
And the response is ordered newest-first within the requested limit
```

#### Type filter

```
Given the caller supplies --type <obs_type>
When the search request is built
Then only observations whose type matches appear in the response
```

#### Project filter

```
Given the caller supplies --project <slug>
When the search request is built
Then only observations belonging to that project appear in the response
```

### Cross-context references

- None. List is contained within the `memory` context's search surface.

## Known caveats

- **There is no dedicated list surface.** List is a CLI-only verb that piggy-backs on search with an empty query. Programmatic callers wanting "list" semantics must invoke search the same way.
- **The fallback matches every live observation.** Observations are saved with a populated body, so the empty-query fallback never excludes a live row.
- **CLI default limit is below the search-surface ceiling.** The CLI defaults `--limit` to 50; the search surface defaults to 20 with an upper bound of 100. The CLI value flows through unmodified.
- **Identity scoping is not applied for CLI list.** The CLI does not forward an identity scope; results include observations from every scope. Programmatic callers that supply a scope get the inclusion-of-unscoped semantics described in `identity-key-ownership`.
- **Type validation lives in the CLI.** Invalid `--type` values are rejected with a usage error before any search request fires.
