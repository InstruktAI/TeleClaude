---
id: 'project/spec/feature/memory/identity-key-ownership'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'internal'
applies_to: 'v1'
status: 'actual'
description: 'Per-row identity ownership for observations — opaque string tagged at save, used at query for inclusion-of-unscoped filtering.'
---

# Identity Key Ownership — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/memory.md

## What it is

Every memory observation carries an optional `identity_key` — an opaque string that tags the row with an identity scope at save time. At query time, callers that supply an `identity_key` see observations tagged with that key PLUS observations with no identity scope (`identity_key IS NULL`). Callers that omit `identity_key` see all observations regardless of scope. v1 owns identity semantics inside the `memory` context: the key is set independently of any centralized identity service, and authorization is not enforced beyond the inclusion rule. The CLI does not expose `--identity-key` — it is reachable only via the HTTP API and the in-process context-injection path consumed by the hook receiver.

## Canonical fields

### Use cases

#### Tag at save (HTTP)

```
Given an HTTP `POST /api/memory/save` body contains `identity_key: <key>`
When `MemoryStore.save_observation` persists the row
Then the `identity_key` column on the row is set to `<key>`
And the row is later visible to any query that supplies the same `<key>` and to any query that supplies no key
```

#### Save without identity tag

```
Given a save request omits `identity_key` (or supplies it as null)
When the row is persisted
Then the `identity_key` column is NULL
And the row is visible to any identity-scoped query (because of the inclusion rule below) and to any non-scoped query
```

#### Inclusion-of-unscoped on search

```
Given a search caller supplies `identity_key=<key>` (HTTP `GET /api/memory/search` parameter)
When `MemorySearch.search` builds its SQL (both FTS5 and LIKE branches)
Then `AND (identity_key IS NULL OR identity_key = :identity_key)` is appended to the WHERE clause
And the response contains observations tagged with `<key>` AND observations with NULL `identity_key`
And observations tagged with any other key are excluded

Given a search caller omits `identity_key`
When `MemorySearch.search` builds its SQL
Then no identity-related predicate is added
And the response contains observations from every identity scope
```

#### Identity scoping on context injection

```
Given the hook receiver resolves a non-null `identity_key` for the session via `derive_identity_key` on the session origin
When it calls `_get_memory_context(project, identity_key=identity_key)` → `generate_context_sync(project, db_path, identity_key=identity_key)`
Then the observations query appends `AND (identity_key IS NULL OR identity_key = :identity_key)` to its WHERE clause
And the rendered Markdown contains observations tagged with `<identity_key>` and observations with NULL scope only
```

```
Given the hook receiver could not resolve an identity for the session
When it calls `_get_memory_context(project)` with no `identity_key`
Then the observations query has no identity predicate
And the rendered Markdown contains observations from every identity scope for that project
```

#### CLI never supplies identity_key

```
Given the CLI handlers `_handle_memories_save`, `_handle_memories_search`, `_handle_memories_list`, `_handle_memories_timeline`, `_handle_memories_delete`
When any of them builds an API call
Then it does NOT pass `identity_key` in the request
And the resulting HTTP call has no identity scope (saves write NULL; queries return rows from every scope)
```

### Implementation pointers (v1)

- Column definition — `teleclaude/core/db_models.py:176` (`identity_key: str | None`)
- `ObservationInput.identity_key` — `teleclaude/memory/types.py:46`
- `SaveObservationRequest.identity_key` — `teleclaude/memory/api_routes.py:29`
- Persisted at save — `teleclaude/memory/store.py:49`
- Search filter (async) — `teleclaude/memory/search.py:94` (FTS5 branch) and `teleclaude/memory/search.py:119` (LIKE branch)
- HTTP `/search` parameter — `teleclaude/memory/api_routes.py:76`
- Context-injection filter (async) — `teleclaude/memory/context/builder.py:82`
- Context-injection filter (sync) — `teleclaude/memory/context/builder.py:45`
- HTTP `/inject` parameter — `teleclaude/memory/api_routes.py:116`
- Hook-receiver identity resolution — `teleclaude/hooks/receiver/__init__.py:194` (`derive_identity_key`)
- Hook-receiver call — `teleclaude/hooks/receiver/__init__.py:355`

### Cross-context references

- `identity` — `derive_identity_key` lives in `teleclaude/core/identity` and is consumed by the hook receiver to resolve a session-scoped identity key before calling the memory context generator. The memory context does not import or depend on the identity context's invariants beyond the opaque string. See `docs/project/spec/domain/identity.md`.

## Known caveats

- **Opaque string, no schema.** v1 treats `identity_key` as a free-form string. There is no FK to an identity table, no validation on shape, and no audit when the same key is used by different callers.
- **`identity_key` is not the v2 `author_principal`.** v2's domain spec replaces this column with `author_principal` (resolved by the `identity` context) and gates updates/deletes by author-or-admin. v1 has no authorization gate (see `observation-delete`) and no rename-on-write protection (the column is just a string at save time). The shift moves identity ownership out of `memory` into `identity` — a cutover-significant change.
- **Inclusion-of-unscoped is intentional asymmetry.** A query scoped to `<key>` sees NULL-scoped rows too; a query scoped to NULL (i.e., omitted) sees all rows. v2 must decide whether to keep this "unscoped-is-public" semantic or replace it with strict per-principal scoping.
- **No filter on `/batch` or `/timeline`.** `POST /api/memory/batch` and `GET /api/memory/timeline` do not accept `identity_key`. A caller that knows an id can fetch the row regardless of how it was tagged at save. `/search` and `/inject` are the only identity-scoped surfaces.
- **CLI is identity-blind.** Every CLI-issued save writes `identity_key=NULL`, and every CLI-issued query sees rows from every identity scope. Only HTTP callers and the hook receiver participate in identity scoping.
- **Renaming on rotation is not modeled.** If a principal's `identity_key` is rotated, prior observations remain tagged with the old key and are no longer visible to queries supplying the new key. There is no migration helper.
