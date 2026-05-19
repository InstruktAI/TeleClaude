---
id: 'project/spec/feature/workflow/todo-removal'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Remove a Todo from todos.db (state, all artifact versions, roadmap entry, and inbound dependency references) and idempotently clean up its git worktree, local branch, and remote branch via a receipt-backed async operation.'
---

# Todo Removal — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

`telec todo remove <slug>` (and the matching `POST /todos/remove`) deletes a Todo's full footprint from `todos.db`: its state row, every artifact and version-history row, its roadmap entry, and any inbound dependency references that other Todos hold on it. For any non-draft Todo, the removal also cascades to physical artifacts on disk — the git worktree at `trees/<slug>/`, the local feature branch, the matching remote branch, the archived `workspace/<slug>/` directory, and binary outputs under `workspace/<slug>/art|html/` (these are archived before deletion). The CLI submits the removal as a receipt-backed durable operation, then polls the receipt with a 30 s estimated timeout until the operation reports `completed`. Every cleanup step is idempotent: missing worktrees, branches, or workspace directories are treated as no-ops, so a partially completed previous removal can be re-run safely.

## Canonical fields

### Use cases

```
Given a Todo "feature-x" exists with state, multiple artifact versions, a roadmap entry, and another Todo "feature-y" that depends on it
When `telec todo remove feature-x` is run
Then `POST /todos/remove` submits a receipt-backed operation and returns 202 immediately
And inside the operation handler, a single DB transaction calls delete_state, delete_artifacts, remove_from_roadmap, and clean_dep_references for "feature-x"
And every artifact row plus its full version history is deleted
And the roadmap entry is removed and "feature-y"'s after-list no longer references "feature-x"
And the daemon notifies "todo_removed"
And the CLI prints "Removed todo: feature-x" after polling the receipt to state="completed"
```

```
Given a Todo whose persisted state has kind="draft" (created via `telec todo create` and not yet promoted)
When `execute_todo_remove` runs
Then the DB rows are removed exactly as for any other Todo
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
Given a holder Todo "parent" whose breakdown lists children ["child-a", "child-b"]
When `telec todo remove parent` is run
Then only the "parent" row, its artifacts, its roadmap entry, and inbound deps pointing at "parent" are removed
And "child-a" and "child-b" stay in todos.db and on the roadmap untouched
And each child must be removed by a separate `telec todo remove` call to be cleaned up
```

```
Given `telec todo remove` is invoked without a slug
When `_handle_todo_remove` parses args
Then it prints the usage banner and exits with status 1
And no API request is made
```

### Implementation pointers (v1)

- `teleclaude/cli/telec/handlers/todo.py:410-459` — `_handle_todo_remove` argv adapter; generates a `client_request_id`, calls `POST /todos/remove`, then `poll_operation` with a 30 s estimated timeout, surfacing the receipt's `state="completed"` or `error` to stdout/stderr
- `teleclaude/api/todo_routes.py:624-643` — `POST /todos/remove` returns 202 and a `SerializedOperation` receipt via `operations.submit_todo_remove`; clearance-gated by `clearance_todos_remove`
- `teleclaude/core/next_machine/remove.py:16-44` — `execute_todo_remove` is the operation handler: resolves `TodosDb` from cwd, classifies the Todo as draft vs. non-draft, runs the DB-side cascade inside one transaction, then `await asyncio.to_thread(cleanup_delivered_slug, cwd, slug)` for non-draft Todos
- `teleclaude/core/todos_db/_state.py:184` — `delete_state` removes the state row
- `teleclaude/core/todos_db/_artifacts.py:384-409` — `delete_artifacts` deletes every `TodoArtifact` row and every `TodoArtifactVersion` row for the slug; no-op when the slug is unknown
- `teleclaude/core/todos_db/_roadmap.py:207-225` — `remove_from_roadmap` deletes the roadmap entry and any `RoadmapDep` rows owned by the slug; returns `False` (no error) when the slug is not in the roadmap
- `teleclaude/core/next_machine/delivery.py:70-106` — `cleanup_delivered_slug` is the idempotent filesystem cascade: archive binary artifacts, `git worktree remove --force`, `git branch -D <branch>`, `git push origin --delete <branch>`, then remove `workspace/<slug>/` (symlink or directory)

### Cross-context references

- `operations` — removal is submitted as a receipt-backed durable operation; the CLI polls the receipt rather than blocking the HTTP call
- `agent_runtime` — `cleanup_delivered_slug` invokes the host `git` toolchain to tear down worktree and branches; remote branch deletion uses a 5 s timeout and tolerates network failure

## Known caveats

- Removal is destructive: the full artifact version history is deleted. There is no soft-delete tier and no built-in undo — once `delete_artifacts` commits, the prior versions are gone from `todos.db`.
- Cleanup is **idempotent by design**, not transactional across the DB-and-filesystem boundary. The DB cascade commits first; the filesystem cascade then runs and may partially fail (logged as warnings). A subsequent re-run of `telec todo remove` finds the DB rows already gone and the filesystem cleanup safely re-walks whatever remains.
- Removing a delivered Todo is allowed and removes the workflow row, but the delivered work itself stays in git history (integration commits and merged branches on `main` are untouched).
- Children of a removed holder are **not** auto-removed. The split relationship is not enforced as a cascade on parent removal; orphaned children remain in the roadmap until removed individually.
- The remote branch delete uses a tight 5 s timeout and is non-fatal — a slow or unreachable origin will not block the operation from reporting completed, but may leave a stale remote branch that must be cleaned up out of band.
- The receipt-backed dispatch means the HTTP 202 returns before the cascade has executed; callers that need a synchronous outcome must poll the receipt (the CLI does this for you with a 30 s estimated timeout).
