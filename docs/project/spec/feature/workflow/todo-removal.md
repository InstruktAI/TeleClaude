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

`telec todo remove <slug>` soft-removes the live Todo entry: the entry becomes `status=removed`, default todo-list/state/artifact/dependency reads hide it immediately, and live dependency edges are scrubbed in both directions. Before that mutation, the shared soft-remove primitive scans snippet `delivered_by` references inside the project-scoped lock and transaction. If the candidate slug is the sole live deliverer of any snippet, removal is refused and no todo-list, state, dependency, or filesystem mutation is committed.

The durable entry, lifecycle state, current artifacts, and every artifact version-history record remain retained by the Todo's durable identity for the retention window. For any non-draft Todo, successful removal still releases physical working resources immediately — the git worktree at `trees/<slug>/`, the local feature branch, the matching remote branch, the archived `workspace/<slug>/` directory, and binary outputs under `workspace/<slug>/art|html/` (these are archived before deletion). The removal is dispatched as a receipt-backed durable operation, and the CLI polls the receipt until the operation reports `completed` or `failed`. Structured removal refusals are persisted on the operation so the CLI can render the affected snippet paths without recomputing state.

<!-- planned:remove-refuses-live-work -->

Before the mutation the removal also guards live work. A removal is refused — before any todo-list, state, dependency, or filesystem mutation — while the slug's claim names a live session other than the caller, an open session other than the caller is bound to the slug, or a non-terminal operation is bound to it. The structured refusal names each holding session and operation so the operator is routed to the holders instead of a wall. A deliberate override flag removes anyway; the override is recorded as such on the durable removed entry. On every removal the claim value present at removal is recorded on the removed entry rather than silently discarded, and slug-keyed dispatch leases are deleted with the removal so a lapsed lease cannot refuse work on a successor Todo that reuses the slug. While the removed entry is retained, artifact writes addressed to the slug are refused with an error that names the removed state, the retention window, and the sanctioned recovery route — distinguishable from a slug that never existed.

<!-- /planned:remove-refuses-live-work -->

A retained removed entry can be reactivated by durable identity before purge, unless an active or icebox entry already owns the same slug. After the retention window elapses, routine maintenance plans any needed snippet reconciliation for the slug — both clearing it from `delivered_by` frontmatter and folding its in-body `planned` / `planned-change` markers with abandon semantics (a `planned` ADD block is dropped with its content and a `planned-change` block reverts to its original side, since the purged work was never delivered) — records the target paths in `pending_purge_paths`, writes and verifies the files, stages and commits only those exact pathspecs, performs staged-set and post-commit verification, then clears `pending_purge_paths` and hard-purges the removed entry by durable identity. Retained state/artifact history cascades to deletion only after that sequence succeeds.

## Canonical fields

### Use cases

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
Given a row "parent" has status holder, with children referencing it by group id
When the operator runs "telec todo remove parent"
Then the removal is refused, naming the row as a holder outside the todo lifecycle
And "parent" and every child are left unchanged
And each child is removed by its own "telec todo remove" call; retiring the last child leaves the holder as context that no longer renders anywhere
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

#### UC-TR-RETENTION-INDEPENDENT: Removed-todo purge window is independent of closed-session retention

```
Given a removed Todo whose removed_at timestamp is 8 days old
And a closed session row whose closed-at marker is 8 days old
When routine maintenance runs
Then the removed Todo entry is hard-purged (its 7-day window has elapsed)
And the closed session row remains retained (its 90-day window has not elapsed)
```

#### UC-TR-SWEEP-SKIPS-NON-CHECKOUT: Retention sweep tolerates a non-checkout trusted directory carrying a legacy todo store

```
Given a trusted directory exists on disk carrying .teleclaude/todos.db
And the directory is not a TeleClaude project checkout
When the removed-todo retention sweep runs
Then the sweep skips the directory without resolving, opening, or creating a todo store for it
And the sweep raises no error for the directory
And project-checkout trusted directories are still swept
```

<!-- planned:remove-refuses-live-work -->

#### UC-TR-REFUSES-LIVE-WORK: Removal refuses while live work holds the slug

```
Given a Todo whose claim names a live session other than the caller, or with an open bound session other than the caller, or with a non-terminal operation bound to it
When the operator runs "telec todo remove <slug>" without the override flag
Then the removal is refused before any todo-list, state, dependency, or filesystem mutation
And the receipt-backed operation stores a structured refusal payload naming each holding session and operation
And the CLI renders the holders from that structured payload and exits non-zero
```

#### UC-TR-OVERRIDE-RECORDED: A deliberate override removes anyway and is recorded

```
Given a Todo whose claim names a live session other than the caller
When the operator runs the removal with the explicit override flag
Then the entry is soft-removed exactly as an unheld Todo is
And the durable removed entry records that the removal was overridden
And the durable removed entry records the claim value the removal displaced
```

#### UC-TR-CLAIM-SURVIVES-ON-TOMBSTONE: The released claim is recorded, never silently discarded

```
Given a Todo whose claim names a session that is no longer live
When the operator runs "telec todo remove <slug>"
Then the removal proceeds without requiring the override flag
And the durable removed entry records the claim value that was released
```

#### UC-TR-LEASE-CLEARED: Slug-keyed dispatch leases do not survive removal

```
Given an open slug-keyed dispatch lease for a Todo
When that Todo is removed
Then the lease is deleted together with the removal
And a successor Todo created under the same slug is not refused work by the predecessor's lease
```

#### UC-TR-REMOVED-SLUG-WRITE-REFUSED: An artifact write to a removed slug names the recoverable state

```
Given a removed Todo inside the retention window and no live Todo owning the same slug
When an agent writes an artifact for that slug
Then the write is refused with an error naming the removed state, the retention window, and the sanctioned recovery route
And the error is distinguishable from the error for a slug that never existed
And "telec todo artifacts write" exits non-zero on the refused write
```

<!-- /planned:remove-refuses-live-work -->

#### UC-TR-REMOVE-CLEANS-PENDING-MARKERS: Removal retires its pending documentation markers

```gherkin
Given an operator has a Todo whose slug owns planned documentation markers across one or more tracked snippet files
And an affected snippet file may already carry unrelated working-tree changes or another slug's pending markers
When the operator runs "telec todo remove <slug>"
Then each affected path's cleanliness is captured before any marker is changed
And only the removed slug's planned additions and planned changes are abandoned
And unrelated content and every other slug's pending markers remain unchanged
And the marker-only cleanup is committed automatically only when every affected path was clean before removal
And otherwise the cleanup remains uncommitted on top of the pre-existing work
And automation-only marker cleanup creates no snippet-review obligation
```


### Cross-context references

- `operations` — removal is submitted as a receipt-backed durable operation; the CLI polls the receipt rather than blocking on the call, and structured refusal payloads survive the operation boundary.
- `agent_runtime` — the delivered-slug cleanup cascade invokes the host `git` toolchain to tear down worktree and branches; remote branch deletion uses a short timeout and tolerates network failure.

## Known caveats

- A removal directive carrying a declared human decision executes unconditionally: the claimant neither verifies the involvement nor defends its todo (`general/policy/leadership` rule 12).
- Removal is recoverable only inside the retention window. Once routine maintenance purges the removed entry, retained lifecycle state, current artifacts, and artifact version history are permanently deleted.
- Reactivation is identity-addressed, not slug-addressed. A slug may have multiple retained removed entries over time, and a live same-slug entry blocks reactivation.
- Soft-remove refuses before mutation when removing the candidate slug would leave a snippet with no live deliverer. Shared-live snippets are allowed; the snippet remains pending until delivery or purge-time reconciliation changes it.
- Cleanup is **idempotent by design**, not transactional across the workflow-and-filesystem boundary. The tombstone commits first; the filesystem cascade then runs and may partially fail (logged as warnings). A subsequent re-run of `telec todo remove` finds no live entry and fails the receipt rather than claiming a second removal.
- Purge-time docs reconciliation is commit-gated. A dirty candidate snippet on a fresh pass leaves `pending_purge_paths` empty and the entry retained. A failed commit or verification failure leaves `pending_purge_paths` populated so the next sweep can distinguish sweep-owned residue from foreign edits.
- Removing a delivered Todo is not part of this surface; removal targets active or icebox entries only. Delivered work stays in git history (integration commits and merged branches on `main` are untouched).

- A holder is not removable: it sits outside the todo lifecycle, and removal targets todos only. Children are removed individually, no cascade runs in either direction, and a holder whose children have all been retired simply stops rendering while its row and frozen artifacts remain as evidence of the split.

<!-- planned:remove-refuses-live-work -->

- Artifact reads addressed to a removed slug return empty content, indistinguishable from an absent artifact; the removed-state refusal applies to artifact writes. The live-work guard reads sessions and operations from the daemon store, so a removal issued while the daemon store is unavailable fails rather than proceeding unguarded.

<!-- /planned:remove-refuses-live-work -->

- The remote branch delete uses a short timeout and is non-fatal — a slow or unreachable origin will not block the operation from reporting completed, but may leave a stale remote branch that must be cleaned up out of band.
- The receipt-backed dispatch means the removal returns before the cascade has executed; callers that need a synchronous outcome must poll the receipt (the CLI does this automatically).
