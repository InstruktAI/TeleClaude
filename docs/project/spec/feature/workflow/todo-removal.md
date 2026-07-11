---
description: 'Soft-remove a Todo from default workflow views while retaining its entry, lifecycle state, artifacts, and artifact version history for a grace window; release working resources immediately, allow identity-addressed reactivation before purge, and hard-purge expired tombstones via routine maintenance.'
visibility: 'public'
---

# Todo Removal — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

<!-- planned-change:fix-telec-todo-remove-silently-deletes-artif -->

`telec todo remove <slug>` soft-removes the live Todo entry: the entry becomes `status=removed`, default todo-list/state/artifact/dependency reads hide it immediately, and live dependency edges are scrubbed in both directions. Before that mutation, the shared soft-remove primitive scans snippet `delivered_by` references inside the project-scoped lock and transaction. If the candidate slug is the sole live deliverer of any snippet, removal is refused and no todo-list, state, dependency, or filesystem mutation is committed.
<!-- change:fix-telec-todo-remove-silently-deletes-artif -->

`telec todo remove <slug>` soft-removes the live Todo entry: the entry becomes `status=removed`, default todo-list and dependency reads hide it immediately, and live dependency edges are scrubbed in both directions. Slug-addressed reads are the exception: artifact read surfaces (content read, listing, metadata, version history, and diff) and the by-slug show payload resolve the most recently removed entry (newest `removed_at`) when no live or delivered Todo owns the slug, with no reveal flag required — a live or delivered same-slug Todo always shadows the removed one. Artifact writes to a removed Todo remain refused. Before the removal mutation, the shared soft-remove primitive scans snippet `delivered_by` references inside the project-scoped lock and transaction. If the candidate slug is the sole live deliverer of any snippet, removal is refused and no todo-list, state, dependency, or filesystem mutation is committed.
<!-- /planned-change:fix-telec-todo-remove-silently-deletes-artif -->

The durable entry, lifecycle state, current artifacts, and every artifact version-history record remain retained by the Todo's durable identity for the retention window. For any non-draft Todo, successful removal still releases physical working resources immediately — the git worktree at `trees/<slug>/`, the local feature branch, the matching remote branch, the archived `workspace/<slug>/` directory, and binary outputs under `workspace/<slug>/art|html/` (these are archived before deletion). The removal is dispatched as a receipt-backed durable operation, and the CLI polls the receipt until the operation reports `completed` or `failed`. Structured removal refusals are persisted on the operation so the CLI can render the affected snippet paths without recomputing state.

A retained removed entry can be reactivated by durable identity before purge, unless an active or icebox entry already owns the same slug. After the retention window elapses, routine maintenance plans any needed snippet reconciliation for the slug — both clearing it from `delivered_by` frontmatter and folding its in-body `planned` / `planned-change` markers with abandon semantics (a `planned` ADD block is dropped with its content and a `planned-change` block reverts to its original side, since the purged work was never delivered) — records the target paths in `pending_purge_paths`, writes and verifies the files, stages and commits only those exact pathspecs, performs staged-set and post-commit verification, then clears `pending_purge_paths` and hard-purges the removed entry by durable identity. Retained state/artifact history cascades to deletion only after that sequence succeeds.

## Canonical fields

### Use cases

<!-- planned-change:fix-telec-todo-remove-silently-deletes-artif -->

```
Given a Todo "feature-x" exists with state, multiple artifact versions, an entry, and another Todo "feature-y" that depends on it
When the operator runs "telec todo remove feature-x"
Then the workflow service submits a receipt-backed operation and returns immediately
And inside the operation handler, the shared soft-remove primitive marks the live entry status=removed
And the entry records removed_at, prev_status, and the outgoing dependency snapshot
And every artifact plus its full version history remains retained by the Todo's durable identity
And "feature-y"'s after-list no longer references "feature-x"
And default reads no longer return "feature-x" by slug
And the CLI reports "Removed todo: feature-x" after polling the receipt to state="completed"
```

<!-- change:fix-telec-todo-remove-silently-deletes-artif -->

```
Given a Todo "feature-x" exists with state, multiple artifact versions, an entry, and another Todo "feature-y" that depends on it
When the operator runs "telec todo remove feature-x"
Then the workflow service submits a receipt-backed operation and returns immediately
And inside the operation handler, the shared soft-remove primitive marks the live entry status=removed
And the entry records removed_at, prev_status, and the outgoing dependency snapshot
And every artifact plus its full version history remains retained by the Todo's durable identity
And "feature-y"'s after-list no longer references "feature-x"
And default todo-list, state, and dependency reads no longer return "feature-x" by slug
And artifact read surfaces continue to return "feature-x"'s retained artifacts by slug
And the CLI reports "Removed todo: feature-x" after polling the receipt to state="completed"
```

<!-- /planned-change:fix-telec-todo-remove-silently-deletes-artif -->

<!-- planned:fix-telec-todo-remove-silently-deletes-artif -->

#### UC-TR-REMOVED-ARTIFACTS-READABLE: Removed-todo retained artifacts stay readable by slug

```
Given a removed Todo "feature-x" whose artifacts and version history are retained
And no active, icebox, or delivered Todo owns slug "feature-x"
When any artifact read surface is asked for "feature-x" — content read, artifact listing, metadata, version history, or diff
Then it resolves the most recently removed "feature-x" entry and returns the retained data
And the by-slug show payload for "feature-x" carries the retained artifact names and metadata with no reveal flag
And an artifact write to "feature-x" is refused as an unknown todo
And when a live Todo later reclaims slug "feature-x", artifact reads resolve the live entry instead
```

#### UC-TR-REMOVED-NEWEST-TOMBSTONE-WINS: Repeated remove/recreate cycles resolve the newest tombstone

```
Given slug "feature-x" was created, given artifacts, and removed twice, leaving two removed entries with distinct artifact content
And no active, icebox, or delivered Todo owns slug "feature-x"
When an artifact read surface is asked for "feature-x"
Then it resolves the removed entry with the newest removed_at
And its version history and diff reads return that entry's retained versions, not the older tombstone's
```

<!-- /planned:fix-telec-todo-remove-silently-deletes-artif -->

```
Given a Todo "feature-x" is the only live deliverer listed in a snippet's delivered_by frontmatter
When the operator runs "telec todo remove feature-x"
Then the shared soft-remove primitive refuses removal before any workflow state mutation
And the receipt-backed operation stores a structured "remove_refused_orphan" payload
And the CLI renders the affected snippet path, slug role, and live-deliverer count from that structured payload
```

```
Given a Todo that has not yet received a worktree or feature branch
When the removal operation runs
Then the entry is soft-removed exactly as for any other Todo
And the delivered-slug cleanup cascade is **skipped** (no worktree, no branch, no workspace teardown)
Because there are no slug-keyed working resources to tear down
```

```
Given a non-draft Todo whose worktree at "trees/<slug>/" was already removed manually
When the delivered-slug cleanup cascade runs as part of removal
Then the worktree-remove step finds the path absent and is a no-op
And the local branch delete runs; failure is logged as a warning, not raised
And the remote branch delete runs with a short timeout; failure is non-fatal
And the workspace directory cleanup tolerates a missing path
And the operation reports completed
```

```
Given a holder entry "parent" with child entries whose group_slug is "parent"
When the operator runs "telec todo remove parent"
Then only the "parent" entry is soft-removed and inbound deps pointing at "parent" are scrubbed
And "child-a" and "child-b" remain in the todo list untouched
And each child must be removed by a separate "telec todo remove" call to be cleaned up
```

```
Given a removed Todo "feature-x" is still inside the retention window
And no active or icebox Todo currently owns slug "feature-x"
When an operator reactivates the removed entry by its durable identity
Then the entry status returns to the pre-removal status when known, or icebox otherwise
And retained outgoing dependency edges are replayed
And state, current artifacts, and artifact version history are visible again through default resolvers
```

```
Given a removed Todo "feature-x" is still inside the retention window
And a newly created active Todo also owns slug "feature-x"
When an operator tries to reactivate the removed entry by its durable identity
Then reactivation fails without mutating either entry
Because same-slug resurrection would collide with the live Todo
```

```
Given a removed Todo's removed_at timestamp is older than the retention window
When routine maintenance runs
Then any snippet delivered_by entries for that slug are planned through the shared reconcile engine
And the sweep persists pending_purge_paths before writing snippet files
And the commit stage is restricted to those exact snippet pathspecs
And staged-set verification runs before commit
And post-commit verification runs before the entry is removed
And pending_purge_paths is cleared before the removed entry is hard-deleted by durable identity
And retained state, current artifacts, and artifact version history cascade to deletion
And no slug-keyed worktree, branch, workspace, or dependency cleanup runs during purge
```

```
Given a previous maintenance pass wrote purge-time snippet changes but failed before finalising the removed entry
When routine maintenance sees pending_purge_paths on the retained removed entry
Then the sweep treats those paths as sweep-owned residue
And if the files already match HEAD, it skips the commit stage and re-runs post-commit verification
And if the files diverge from HEAD, it re-applies the planned snippet mutation and retries the exact-pathspec commit sequence
```

#### UC-TR-PURGE-STRIPS-INBODY-MARKERS: Purge folds the slug's in-body markers with abandon semantics

```
Given a snippet body carries the purged slug in a planned ADD block and in a planned-change block
And another slug's in-body marker is present in the same snippet
When routine maintenance reconciles snippets for the hard-purged slug
Then the purged slug's planned ADD block is removed together with its wrapped content
And the purged slug's planned-change block reverts to its original side, discarding the replacement
And the other slug's in-body marker is left unchanged
And a subsequent liveness scan over the result reports no finding for the purged slug
```

```
Given "telec todo remove" is invoked without a slug
When the CLI parses args
Then it prints the usage banner and exits with status 1
And no removal request is made
```

<!-- planned:tui-creator-session-link -->

#### UC-TR-RETENTION-INDEPENDENT: Removed-todo purge window is independent of closed-session retention

```
Given a removed Todo whose removed_at timestamp is 8 days old
And a closed session row whose closed-at marker is 8 days old
When routine maintenance runs
Then the removed Todo entry is hard-purged (its 7-day window has elapsed)
And the closed session row remains retained (its 90-day window has not elapsed)
```

<!-- /planned:tui-creator-session-link -->

### Cross-context references

- `operations` — removal is submitted as a receipt-backed durable operation; the CLI polls the receipt rather than blocking on the call, and structured refusal payloads survive the operation boundary.
- `agent_runtime` — the delivered-slug cleanup cascade invokes the host `git` toolchain to tear down worktree and branches; remote branch deletion uses a short timeout and tolerates network failure.

## Known caveats

- Removal is recoverable only inside the retention window. Once routine maintenance purges the removed entry, retained lifecycle state, current artifacts, and artifact version history are permanently deleted.
- Reactivation is identity-addressed, not slug-addressed. A slug may have multiple retained removed entries over time, and a live same-slug entry blocks reactivation.
- Soft-remove refuses before mutation when removing the candidate slug would leave a snippet with no live deliverer. Shared-live snippets are allowed; the snippet remains pending until delivery or purge-time reconciliation changes it.
- Cleanup is **idempotent by design**, not transactional across the workflow-and-filesystem boundary. The tombstone commits first; the filesystem cascade then runs and may partially fail (logged as warnings). A subsequent re-run of `telec todo remove` finds no live entry and fails the receipt rather than claiming a second removal.
- Purge-time docs reconciliation is commit-gated. A dirty candidate snippet on a fresh pass leaves `pending_purge_paths` empty and the entry retained. A failed commit or verification failure leaves `pending_purge_paths` populated so the next sweep can distinguish sweep-owned residue from foreign edits.
- Removing a delivered Todo is not part of this surface; removal targets active or icebox entries only. Delivered work stays in git history (integration commits and merged branches on `main` are untouched).
- Children of a removed holder are **not** auto-removed. The split relationship is not enforced as a cascade on parent removal; orphaned children remain in the todo list until removed individually.
- The remote branch delete uses a short timeout and is non-fatal — a slow or unreachable origin will not block the operation from reporting completed, but may leave a stale remote branch that must be cleaned up out of band.
- The receipt-backed dispatch means the removal returns before the cascade has executed; callers that need a synchronous outcome must poll the receipt (the CLI does this automatically).
