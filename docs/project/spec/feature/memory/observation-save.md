---
id: 'project/spec/feature/memory/observation-save'
type: 'spec'
domain: 'software-development'
scope: 'project'
applies_to: 'v1'
status: 'actual'
visibility: 'internal'
description: 'Save a memory observation — auto-titled, default-project-scoped, identity-tagged, and slotted into a per-project manual session.'
---

# Observation Save — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/memory.md

## What it is

The save path is how a memory observation enters v1's durable store. A caller — a human via `telec memories save`, an agent via the daemon's HTTP API, or any other HTTP consumer — supplies a `text` body plus optional `title`, `type`, `project`, and `identity_key`. The save path resolves project scoping (falling back to `teleclaude` when none is supplied), derives a title from the text when none is given, ensures a per-project manual session exists, and inserts a row into `memory_observations`. The persisted observation is identified by an auto-increment integer `id` and returned to the caller alongside its resolved title and project.

## Canonical fields

### Use cases

#### Save via CLI

```
Given a human or agent runs `telec memories save "<text>" [--title <t>] [--type <obs_type>] [--project <slug>]`
When the CLI builds the request body
Then it includes `text`; includes `title` only if `--title` was given; includes `type` only if `--type` was given; includes `project` only if `--project` was given
And POSTs the body to `/api/memory/save` on the daemon
And on success prints `Saved observation #<id> — <title> (project: <project>)`
```

#### Save via HTTP

```
Given any HTTP caller sends `POST /api/memory/save` with body `{"text": "<text>"}`
When the daemon receives the request
Then it constructs an `ObservationInput` with `type` defaulted to `discovery` when the body omits `type`
And resolves `project` to `teleclaude` when the body omits `project`
And derives a `title` from the text when the body omits `title`
And returns `{"id": <int>, "title": <resolved_title>, "project": <resolved_project>}` with HTTP 200
```

#### Default project fallback

```
Given a save request omits `project`
When the store resolves project scoping
Then `project` is set to the literal string `teleclaude`
And the observation is persisted under that project
```

#### Auto-title derivation

```
Given a save request omits `title`
When the store derives a title from the text
Then the first line after trimming surrounding whitespace is used as the source text
And the store scans for `.` first, then `!`, then `?`, returning the first matching separator whose position is greater than 0 and less than 80 (inclusive of the punctuation)
And if no scanned separator qualifies, the first 80 characters are taken verbatim
And the derived string is persisted as `title`
```

#### Manual-session-per-project reuse

```
Given the project has no row in `memory_manual_sessions`
When the store saves the first observation for that project
Then a new `memory_session_id` UUID is generated and inserted into `memory_manual_sessions` with the project key
And the new observation is linked to that `memory_session_id`

Given the project already has a row in `memory_manual_sessions`
When the store saves another observation for that project
Then the existing `memory_session_id` is reused on the new observation
And no new row is inserted into `memory_manual_sessions`
```

#### Identity tagging at save

```
Given a save request supplies a non-null `identity_key`
When the store persists the observation
Then the `identity_key` column on the row is set to that value
And the observation can later be retrieved by queries that filter on the same identity scope (see `identity-key-ownership`)
```

```
Given a save request omits `identity_key` (or supplies it as null)
When the store persists the observation
Then the `identity_key` column on the row is left NULL (unscoped)
And the observation can later be retrieved by ANY identity-scoped query plus identity-less queries (see `identity-key-ownership`)
```

### Implementation pointers (v1)

- `MemoryStore.save_observation` — `teleclaude/memory/store.py:27`
- Default-project fallback — `teleclaude/memory/store.py:21` (`DEFAULT_PROJECT = "teleclaude"`)
- Auto-title derivation — `teleclaude/memory/store.py:197` (`_auto_title`)
- Manual-session-per-project reuse — `teleclaude/memory/store.py:146` (`_get_or_create_manual_session`)
- HTTP entry — `teleclaude/memory/api_routes.py:51` (`POST /api/memory/save`)
- CLI entry — `teleclaude/cli/telec/handlers/memories.py:357` (`_handle_memories_save`)
- CLI → API transport — `teleclaude/cli/api_client.py:824` (`memory_save`)
- Persisted row schema — `teleclaude/core/db_models.py:155` (`MemoryObservation`)
- Router mount — `teleclaude/api_server.py:144`

### Cross-context references

- `identity` — supplies the `identity_key` semantics consumed at save (HTTP body); see `docs/project/spec/domain/identity.md` and `identity-key-ownership`.
- `agent_runtime` — the hook receiver does NOT save observations; it only reads them via the context-injection path. See `docs/project/spec/domain/agent_runtime.md` and `memory-context-injection`.

## Known caveats

- **No event emitted on save.** v1 produces no `memory.observation.saved` event. The v2 domain spec describes such an event; v1 simply commits the row and returns. Consumers wanting to react to new observations must poll.
- **No author principal recorded.** v1's `MemoryObservation` has no `author_principal` column. Identity is recorded via the looser `identity_key` string (see `identity-key-ownership`). v2's domain spec introduces `author_principal`; the rename + ownership shift is a v2 cutover decision.
- **`title` and `text` are stored in different columns.** The text body is persisted as `narrative` on the row, not `body`. v2 renames `narrative` → `body`.
- **The CLI does NOT expose `--identity-key`.** Only HTTP callers and the in-process context-injection path can supply or read identity scope. CLI-saved observations are always unscoped (`identity_key IS NULL`).
- **Integer auto-increment ID.** Observations are identified by a SQLite/SQL integer `id`, not a UUID. v2 uses `observation_id` UUID.
- **No update path.** v1 has no save-update verb. Once persisted, an observation's fields cannot be modified; the only mutations are delete (see `observation-delete`) and FTS5 trigger-driven re-indexing. v2's UC-MEM-5 update path has no v1 equivalent.
