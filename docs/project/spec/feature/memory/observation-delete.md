---
id: 'project/spec/feature/memory/observation-delete'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'internal'
applies_to: 'v1'
status: 'actual'
description: 'Delete a memory observation by integer id, returning 404 when nothing matched.'
---

# Observation Delete — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/memory.md

## What it is

A memory observation can be removed by its integer `id`. The path issues a single `DELETE FROM memory_observations WHERE id = :id`; the SQLite FTS5 triggers attached to the table propagate the removal to `memory_observations_fts` automatically. The HTTP endpoint reports 404 when no row matched, and the CLI surfaces this as a printed error. No authorization is enforced; any caller able to reach the daemon's HTTP surface can delete any observation.

## Canonical fields

### Use cases

#### Delete via CLI

```
Given a human or agent runs `telec memories delete <id>`
When the CLI parses arguments
Then `<id>` must be parseable as an integer (otherwise the CLI prints "Invalid ID '<id>': must be a number." and exits 1)
And the CLI calls `DELETE /api/memory/<id>` on the daemon
And on success prints `Deleted observation #<id>`
And on `APIError` (any non-2xx) prints `Error: <detail>` and exits 1
```

#### Delete via HTTP

```
Given any HTTP caller sends `DELETE /api/memory/<observation_id>`
When the daemon's `delete_observation` handler runs
Then it calls `MemoryStore.delete_observation(observation_id)`
And on success returns HTTP 200 with body `{"deleted": <observation_id>}`
And on no-match raises HTTP 404 with detail `Observation not found`
```

#### Store-level delete

```
Given a `DELETE` request reaches the store
When `MemoryStore.delete_observation` executes
Then it issues `DELETE FROM memory_observations WHERE id = :id`
And commits the transaction
And returns True if the result reported `rowcount > 0`, False otherwise
And the FTS5 trigger `memory_obs_ad` removes the corresponding row from `memory_observations_fts`
```

### Implementation pointers (v1)

- `MemoryStore.delete_observation` — `teleclaude/memory/store.py:92`
- HTTP entry — `teleclaude/memory/api_routes.py:105` (`DELETE /api/memory/{observation_id}`)
- CLI entry — `teleclaude/cli/telec/handlers/memories.py:373` (`_handle_memories_delete`)
- CLI parsing — `teleclaude/cli/telec/handlers/memories.py:234` (`_parse_memories_delete_args`)
- CLI → API transport — `teleclaude/cli/api_client.py:846` (`memory_delete`)
- FTS5 delete trigger — `teleclaude/core/migrations/001_initial_schema.py:343` (`memory_obs_ad`)

### Cross-context references

- None. Delete is contained within the `memory` context.

## Known caveats

- **No event emitted on delete.** v1 produces no `memory.observation.deleted` event. Subscribers that want to react to deletions must poll.
- **No authorization check.** v1 enforces no author-or-admin authorization on delete (the v2 domain spec calls for "author or authorized operator"). Any HTTP caller can delete any observation by id.
- **No bulk delete surface.** Deletion is one-at-a-time. There is no batch endpoint analogous to `/batch` for delete.
- **Hard delete only.** v1 has no soft-delete / tombstone behavior. The row is removed; the FTS5 row is removed; the id will never be reused (SQLite `INTEGER PRIMARY KEY` semantics) but no audit record survives.
- **Idempotency surfaces as 404.** Calling `DELETE /api/memory/<id>` twice returns 200 the first time and 404 the second. Callers needing idempotent semantics should treat 404 as success on retry.
