---
id: 'project/spec/feature/workflow/artifact-versioning'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'target'
delivered_by:
  - drift-detection-consolidation
description: 'Multi-version storage of workflow Artifacts in todos.db — every write appends a new version row keyed by SHA256 digest, current pointer updates in place, diffs are computed between digests, and remove cascades version history.'
---

# Workflow Artifact Versioning — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

The Artifact aggregate inside the `workflow` bounded context persists every Artifact write (PRD, architecture, test-specs, implementation-plan, etc.) as a content-addressed version row in `todos.db`. Each write computes the SHA256 digest of the content, appends a row to `todo_artifact_versions`, and updates the `todo_artifacts` current-version pointer in place. Previous versions remain addressable by digest so the system can render unified diffs between any two versions on demand.

Artifact provenance — the `origin/main` SHA at write time (captured via `get_origin_main_sha(cwd)`, never local HEAD) and the workspace paths referenced by the artifact body — is captured alongside the digest, but it is stored on the Todo's state (the `ArtifactEntry` lifecycle stamp), not on the artifact rows themselves. The artifact tables stay narrow: id, slug, name, content, digest, updated_by, timestamps. The lifecycle stamp itself is the carrier of the extended drift-evidence fields (`upstream_digests`, `owned_snippet_digests`, `referenced_snippet_digests`, `dependency_set_at_write`, `produced_at`) — see `@spec/feature/workflow/drift-detection` for their per-class semantics and the single `_sync_artifact_digest_state` boundary that populates them.

Removal of an artifact deletes both the current row and the full version history in a single transaction. Artifact kinds are enumerated; the canonical list is enforced at the CLI boundary before any DB write. Each artifact kind is unique per Todo (one `prd` per slug, one `implementation-plan` per slug, etc.).

## Canonical fields

### Use cases

```
Given an active todo "my-feature" with no prd artifact
When an agent runs `telec todo artifacts write my-feature prd "<content>"`
Then workflow computes the SHA256 digest of the content
And inserts a new row into todo_artifact_versions tagged with the digest, slug, name, content, updated_by, created_at
And upserts the todo_artifacts row pointing at the new content + digest + updated_at
And the route refreshes the codebase_sha_at_write and referenced_paths stamps on the todo's state
```

```
Given an active todo with an existing prd artifact at digest D1
When an agent writes a second prd revision producing digest D2
Then workflow appends a new version row for D2 without mutating the D1 row
And the todo_artifacts current pointer advances to D2
And `telec todo artifacts read my-feature prd` returns the D2 content
And both D1 and D2 remain individually addressable for diff
```

```
Given an artifact has two versions with digests D1 and D2
When an agent runs `telec todo artifacts diff my-feature prd <D1> <D2>`
Then workflow loads both version bodies by digest
And returns a unified diff with headers "prd@<D1[:12]>" and "prd@<D2[:12]>"
And returns the empty string when D1 == D2 (after confirming the digest exists)
```

```
Given an agent runs `telec todo artifacts diff` with a digest the artifact never had
When workflow looks up the digest
Then it raises ValueError and the API surfaces 404 with the unknown digest in the detail
```

```
Given a todo has an architecture artifact with several historical versions
When an agent runs `telec todo artifacts remove my-feature architecture`
Then workflow deletes the todo_artifacts row and every todo_artifact_versions row for (id, "architecture") in a single transaction
And the API response reports removed=true plus the versions_deleted count
And subsequent reads return empty content; subsequent diffs raise ValueError
```

```
Given an agent attempts `telec todo artifacts write my-feature unknown-kind ...`
When the CLI validates the artifact name against ARTIFACT_NAMES
Then it rejects the call with "Unknown artifact name" and the canonical list before any DB write
```

```
Given a todo whose roadmap entry is in status=delivered
When an agent attempts to write any artifact for that slug
Then `_ensure_artifact_id` raises ValueError("…is delivered (read-only)") and the API surfaces an error
```

### Implementation pointers (v1)

- `teleclaude/core/todos_db/_artifacts.py:27` — `_sha256` content digest helper
- `teleclaude/core/todos_db/_artifacts.py:112` — `write_artifact`: append version row + upsert current pointer
- `teleclaude/core/todos_db/_artifacts.py:259` — `list_artifacts`: artifact names for a slug ordered by name
- `teleclaude/core/todos_db/_artifacts.py:270` — `artifact_versions`: history newest-first, capped by limit
- `teleclaude/core/todos_db/_artifacts.py:297` — `delete_artifact`: removes current row + every version row
- `teleclaude/core/todos_db/_artifacts.py:342` — `artifacts_diff`: unified diff between two digests; raises on unknown digest
- `teleclaude/core/todos_db/schema.sql:29` — `todo_artifacts` (current-version pointer table)
- `teleclaude/core/todos_db/schema.sql:40` — `todo_artifact_versions` (append-only history)
- `teleclaude/cli/telec/handlers/todo.py:467` — `_validate_artifact_name` enforces the canonical kinds list
- `teleclaude/cli/telec/handlers/todo.py:475` — `_handle_todo_artifacts` dispatcher (list/read/write/diff/remove)
- `teleclaude/api/todo_routes.py:329` — `/todos/artifacts/{slug}/{name}` REST surface (read/write/remove)
- `teleclaude/api/todo_routes.py:284` — `_sync_artifact_digest_state` stamps codebase_sha + referenced_paths onto todo state

### Cross-context references

- `integration` — drift analysis reads each artifact's `codebase_sha_at_write` and `referenced_paths` from the Todo's state (not from the artifact row) to detect codebase drift since the artifact was authored.
- `next_machine` — artifact presence and digests drive lifecycle phase readiness (e.g., a non-empty `prd` digest advances the prepare state machine out of intake).

## Known caveats

- The `codebase_sha_at_write` and `referenced_paths` fields live on the Todo's state (`ArtifactEntry` in `teleclaude/types/todos.py:156`), not on the artifact rows themselves. The artifact tables intentionally stay narrow (content + digest + audit columns); provenance is a Todo-state concern refreshed by `_sync_artifact_digest_state` only for the lifecycle-relevant artifact kinds (`input`, `prd`, `requirements`, `architecture`, `test-specs`, `implementation-plan`).
- The `input` artifact has special status: once `requirements` exists, the write route rejects further `input` writes with HTTP 409 ("input artifact is frozen"), and `telec todo artifacts remove input` is unconditionally rejected.
- Diff lookup is digest-keyed, not chronological — callers must already know the two digests. The `artifact_versions` listing is the source for valid digests.
- Removing an artifact is destructive: the full version history is lost in the same transaction. There is no undo.
- Artifact writes against a delivered todo are blocked at `_ensure_artifact_id` to keep delivered todos read-only.
- The CLI write path constructs the `codebase_sha_at_write` and `referenced_paths` request body by calling `get_origin_main_sha` (the canonical drift anchor per `@spec/feature/workflow/drift-detection`, replacing the prior `get_head_commit` call) and `extract_referenced_paths` against the invocation cwd; the API uses those if supplied, otherwise recomputes them server-side via the same `get_origin_main_sha` helper.
- `list_artifacts` returns names only; version metadata (digest, timestamps) requires a follow-up `artifact_versions` call.
