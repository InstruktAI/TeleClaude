---
id: 'project/spec/feature/workflow/todo-removal'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Soft-remove a Todo from default workflow views while retaining its roadmap row, lifecycle state, artifacts, and artifact version history for a grace window; release working resources immediately, allow row-id reactivation before purge, and hard-purge expired tombstones via routine maintenance.'
---

# Todo Removal — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

`telec todo remove <slug>` (and the matching `POST /todos/remove`) soft-removes the live Todo row in `todos.db`: the roadmap entry becomes `status=removed`, default roadmap/state/artifact/dependency reads hide it immediately, and live dependency edges are scrubbed in both directions. Before that mutation, the shared soft-remove primitive scans snippet `delivered_by` references inside the project-scoped lock and DB transaction. If the candidate slug is the sole live deliverer of any snippet, removal is refused and no roadmap, state, dependency, or filesystem mutation is committed.

The durable row, lifecycle state, current artifacts, and every artifact version-history row remain retained by the Todo row id for the retention window. For any non-draft Todo, successful removal still releases physical working resources immediately — the git worktree at `trees/<slug>/`, the local feature branch, the matching remote branch, the archived `workspace/<slug>/` directory, and binary outputs under `workspace/<slug>/art|html/` (these are archived before deletion). The CLI submits the removal as a receipt-backed durable operation, then polls the receipt with a 30 s estimated timeout until the operation reports `completed` or `failed`. Structured removal refusals are persisted on the operation as `error_payload` so the CLI can render the affected snippet paths without recomputing state.

A retained removed row can be reactivated by durable row id before purge, unless an active or icebox row already owns the same slug. After the retention window elapses, routine maintenance plans any needed snippet `delivered_by` removals, records the target paths in `pending_purge_paths`, writes and verifies the files, stages and commits only those exact pathspecs, performs staged-set and post-commit verification, then clears `pending_purge_paths` and hard-purges the removed row by id. Cascading foreign keys delete its retained state/artifact history only after that sequence succeeds.

## Canonical fields

### Use cases

```
Given a Todo "feature-x" exists with state, multiple artifact versions, a roadmap entry, and another Todo "feature-y" that depends on it
When `telec todo remove feature-x` is run
Then `POST /todos/remove` submits a receipt-backed operation and returns 202 immediately
And inside the operation handler, the shared soft-remove primitive marks the live roadmap row status=removed
And the row records removed_at, prev_status, and the outgoing dependency snapshot
And every artifact row plus its full version history remains retained by the Todo row id
And "feature-y"'s after-list no longer references "feature-x"
And default reads no longer return "feature-x" by slug
And the daemon notifies "todo_removed"
And the CLI prints "Removed todo: feature-x" after polling the receipt to state="completed"
```

```
Given a Todo "feature-x" is the only live deliverer listed in a snippet's delivered_by frontmatter
When `telec todo remove feature-x` is run
Then the shared soft-remove primitive refuses removal before mutating todos.db
And the receipt-backed operation stores error_payload kind="remove_refused_orphan"
And the CLI renders the affected snippet path, slug role, and live-deliverer count from that structured payload
```

```
Given a Todo whose persisted state has kind="draft" (created via `telec todo create` and not yet promoted)
When `execute_todo_remove` runs
Then the DB row is soft-removed exactly as for any other Todo
And `cleanup_delivered_slug` is **skipped** (no worktree, no branch, no workspace teardown)
Because draft Todos never received a worktree or feature branch in the first place
```

```
Given a non-draft Todo whose worktree at `trees/<slug>/` was already removed manually
When `cleanup_delivered_slug` runs as part of removal
Then the worktree-remove step finds the path absent and is a no-op
And the local `git branch -D <slug>` runs; failure is logged as a warning, not raised
And the remote `git push origin --delete <slug>` runs with a 5 s timeout; failure is non-fatal
And the workspace directory cleanup tolerates a missing path
And the operation reports completed
```

```
Given a holder roadmap row "parent" with child rows whose group_slug is "parent"
When `telec todo remove parent` is run
Then only the "parent" row is soft-removed and inbound deps pointing at "parent" are scrubbed
And "child-a" and "child-b" stay in todos.db and on the roadmap untouched
And each child must be removed by a separate `telec todo remove` call to be cleaned up
```

```
Given a removed Todo "feature-x" is still inside the retention window
And no active or icebox Todo currently owns slug "feature-x"
When an operator reactivates the removed row by its durable row id
Then the roadmap status returns to the pre-removal status when known, or icebox otherwise
And retained outgoing dependency edges are replayed
And state, current artifacts, and artifact version history are visible again through default resolvers
```

```
Given a removed Todo "feature-x" is still inside the retention window
And a newly created active Todo also owns slug "feature-x"
When an operator tries to reactivate the removed row by id
Then reactivation fails without mutating either row
Because same-slug resurrection would collide with the live Todo
```

```
Given a removed Todo's removed_at timestamp is older than the retention window
When routine maintenance runs
Then any snippet delivered_by entries for that slug are planned through the shared reconcile engine
And the sweep persists pending_purge_paths before writing snippet files
And git add and git commit are restricted to those exact snippet pathspecs
And staged-set verification runs before commit
And post-commit verification runs before the row is deleted
And pending_purge_paths is cleared before the removed row is hard-deleted by durable row id
And cascading foreign keys delete its retained state, current artifacts, and artifact version history
And no slug-keyed worktree, branch, workspace, or dependency cleanup runs during purge
```

```
Given a previous maintenance pass wrote purge-time snippet changes but failed before finalising the removed row
When routine maintenance sees pending_purge_paths on the retained removed row
Then the sweep treats those paths as sweep-owned residue
And if the files already match HEAD, it skips git add and git commit and re-runs post-commit verification
And if the files diverge from HEAD, it re-applies the planned snippet mutation and retries the exact-pathspec commit sequence
```

```
Given `telec todo remove` is invoked without a slug
When `_handle_todo_remove` parses args
Then it prints the usage banner and exits with status 1
And no API request is made
```

### Implementation pointers (v1)

- `teleclaude/cli/telec/handlers/todo.py:336-419` — `_handle_todo_remove` argv adapter; generates a `client_request_id`, calls `POST /todos/remove`, then `poll_operation` with a 30 s estimated timeout, surfacing `completed` receipts to stdout and structured remove-refusal payloads to stderr
- `teleclaude/api/todo_routes.py:711-714` — `POST /todos/remove` returns 202 and a `SerializedOperation` receipt via `operations.submit_todo_remove`; clearance-gated by `clearance_todos_remove`
- `teleclaude/api_models.py:230-274` — operation status DTO and payload expose additive `error_payload` data for structured failures
- `teleclaude/core/operations/service.py:600-668` — operation execution persists `OperationFailure.to_error_payload()` alongside the existing text error
- `teleclaude/core/next_machine/remove.py:16-44` — `execute_todo_remove` is the operation handler: resolves `TodosDb` from cwd, routes to the shared soft-remove primitive, and fails the receipt-backed operation when no live row was removed
- `teleclaude/docs_reconcile.py:34-47` — typed snippet write plans and removal-refusal snippet summaries
- `teleclaude/docs_reconcile.py:125-177` — `scan_remove_orphans()` reads snippet frontmatter before soft-remove mutation
- `teleclaude/docs_reconcile.py:255-267` — `reconcile_snippets_for_purged_slugs()` plans purge-time frontmatter updates without writing files
- `teleclaude/core/todos_db/_exceptions.py:31-65` — structured operation failure and remove-refusal payload contracts
- `teleclaude/core/todos_db/_roadmap.py:290-377` — `soft_remove_from_roadmap` owns the snippet orphan scan, tombstone mutation, dependency scrub, draft detection, mutation notification, and immediate slug-keyed working-resource cleanup for non-drafts
- `teleclaude/core/todos_db/_roadmap.py:381-485` — `reactivate_removed` restores a retained removed row by durable row id, fail-closed on missing/non-removed rows, live same-slug collisions, and malformed tombstone dependency payloads
- `teleclaude/core/todos_db/_roadmap.py:489-580` — retention primitives list expired removed rows, persist/clear `pending_purge_paths`, delete one row by durable id, and preserve the compatibility wrapper
- `teleclaude/core/todos_db/_state.py` and `teleclaude/core/todos_db/_artifacts.py` — default state/artifact resolvers gate through live active/icebox roadmap rows, so removed rows are hidden until reactivation
- `teleclaude/core/next_machine/delivery.py:70-106` — `cleanup_delivered_slug` is the idempotent filesystem cascade: archive binary artifacts, `git worktree remove --force`, `git branch -D <branch>`, `git push origin --delete <branch>`, then remove `workspace/<slug>/` (symlink or directory)
- `teleclaude/services/maintenance_service.py:199-363` — per-row purge commit path persists `pending_purge_paths`, exact-pathspec stages and commits, verifies staged and working-tree state, clears the durable retry marker, then purges the removed row
- `teleclaude/services/maintenance_service.py:464-509` — hourly maintenance opens each trusted project and applies the shared retention window to removed todos

### Cross-context references

- `operations` — removal is submitted as a receipt-backed durable operation; the CLI polls the receipt rather than blocking the HTTP call, and structured refusal payloads survive the operation boundary
- `agent_runtime` — `cleanup_delivered_slug` invokes the host `git` toolchain to tear down worktree and branches; remote branch deletion uses a 5 s timeout and tolerates network failure

## Known caveats

- Removal is recoverable only inside the retention window. Once routine maintenance purges the removed row, retained lifecycle state, current artifacts, and artifact version history are permanently deleted.
- Reactivation is row-id-addressed, not slug-addressed. A slug may have multiple retained removed rows over time, and a live same-slug row blocks reactivation.
- Soft-remove refuses before mutation when removing the candidate slug would leave a snippet with no live deliverer. Shared-live snippets are allowed; the snippet remains target/mixed until delivery or purge-time reconciliation changes it.
- Cleanup is **idempotent by design**, not transactional across the DB-and-filesystem boundary. The DB tombstone commits first; the filesystem cascade then runs and may partially fail (logged as warnings). A subsequent re-run of `telec todo remove` finds no live row and fails the receipt rather than claiming a second removal.
- Purge-time docs reconciliation is commit-gated. A dirty candidate snippet on a fresh pass leaves `pending_purge_paths` NULL and the row retained. A failed commit or verification failure leaves `pending_purge_paths` populated so the next sweep can distinguish sweep-owned residue from foreign edits.
- Removing a delivered Todo is not part of this surface; removal targets active or icebox rows only. Delivered work stays in git history (integration commits and merged branches on `main` are untouched).
- Children of a removed holder are **not** auto-removed. The split relationship is not enforced as a cascade on parent removal; orphaned children remain in the roadmap until removed individually.
- The remote branch delete uses a tight 5 s timeout and is non-fatal — a slow or unreachable origin will not block the operation from reporting completed, but may leave a stale remote branch that must be cleaned up out of band.
- The receipt-backed dispatch means the HTTP 202 returns before the cascade has executed; callers that need a synchronous outcome must poll the receipt (the CLI does this for you with a 30 s estimated timeout).
