---
description: 'Soft-remove a Todo from default workflow views while retaining its entry, lifecycle state, artifacts, and artifact version history for a grace window; release working resources immediately, allow identity-addressed reactivation before purge, and hard-purge expired tombstones via routine maintenance.'
visibility: 'public'
---

# Todo Removal — Spec

## Required reads

- docs/global/sdlc/principle/domain-driven-design.md
- docs/global/sdlc/spec/domain-spec.md
- @docs/local/spec/domain/workflow.md

## What it is

`telec todo remove <slug>` soft-removes the live Todo entry: the entry becomes `status=removed`, default todo-list/state/dependency reads hide it immediately while its retained artifacts stay readable until purge, and live dependency edges are scrubbed in both directions. Before that mutation, the shared soft-remove primitive plans abandonment of every pending documentation carrier, captures the exact reversible material with the retained Todo, and refuses the transition if any affected source cannot be resolved, written, or committed safely. Abandonment touches only the removed slug's pending additions, changes, companions, and `delivered_by` memberships, under the abandonment rule `local/projects/teleclaude/spec/feature/context/lifecycle-marker-reconciliation` owns; removal never refuses because the removed slug is a pending snippet's only deliverer. Unrelated content and other slugs' pending material remain untouched, and automation-only cleanup creates no snippet-review obligation. A successful removal therefore makes the tombstone and its abandoned documentation state durable together; failure names the slug, source path, line, and reason without reporting removal success.

The durable entry, lifecycle state, current artifacts, and every artifact version-history record remain retained by the Todo's durable identity for the retention window. For any non-draft Todo, successful removal still releases physical working resources immediately — the git worktree at `trees/<slug>/`, the local feature branch, the matching remote branch, the archived `workspace/<slug>/` directory, and binary outputs under `workspace/<slug>/art|html/` (these are archived before deletion). Missing working resources and branch-cleanup failures do not prevent removal from completing. The worktree is detached from its active location into a uniquely named entry in the project's worktree trash area on the same filesystem; removal completion does not wait for that entry's recursive deletion. The daemon's existing maintenance pass reclaims detached entries at startup and periodically, off the event loop. The removal is dispatched as a receipt-backed durable operation: the CLI prints the receipt and exits without waiting. Structured removal refusals are persisted on the failed operation, so the outcome carries the holding sessions and operations without recomputing state.

Before the mutation the removal also guards live work. A removal is refused — before any todo-list, state, dependency, or filesystem mutation — while the slug's claim names a live session other than the caller, an open session other than the caller is bound to the slug, or a non-terminal operation is bound to it. The structured refusal names each holding session and operation so the operator is routed to the holders instead of a wall. A deliberate override flag removes anyway; the override is recorded as such on the durable removed entry. On every removal the claim value present at removal is recorded on the removed entry rather than silently discarded. A caller whose session is bound to the removed slug is released from that binding by the removal, so it can go on to drive another Todo. While the removed entry is retained, artifact writes addressed to the slug are refused with an error that names the removed state, the retention window, and the sanctioned recovery route — distinguishable from a slug that never existed.

A retained removed entry can be reactivated by durable identity before purge, unless an active or icebox entry already owns the same slug. Reactivation restores the exact captured documentation material as pending before the Todo returns to its pre-removal status, or to icebox when its prior status is unavailable; an unsafe restoration faults and leaves the Todo removed. A same-slug collision refuses without mutating either entry. The Todo retention window is independent of closed-session retention. After the retention window elapses, routine maintenance verifies that abandonment is complete, clears the retained restoration material, and hard-purges the removed entry by durable identity. Purge-time documentation reconciliation abandons only that Todo's remaining pending material, under the same rule as removal, leaves other slugs' markers unchanged, and does not repeat worktree, branch, workspace, or dependency cleanup. The retention sweep opens todo stores only for valid project checkouts. Retained state and artifact history cascade to deletion only after that sequence succeeds. The purge sequence keeps the removed entry and its retained material until documentation abandonment is complete; an interrupted purge can resume without treating unrelated changes as its own.

## Canonical fields

### Use cases

#### UC-TR-REMOVE-UNWANTED: Remove a Todo that is no longer wanted

#### UC-TR-REACTIVATES-PENDING: Reactivate removed work during its recovery window

```gherkin
Given a removed Todo "feature-x" is still inside the retention window
And no active or icebox Todo currently owns slug "feature-x"
When an operator reactivates the removed entry by its durable identity
Then the Todo is restored for work with its retained content and pending documentation available again
```

#### UC-TR-PURGE-STRIPS-INBODY-MARKERS: Purge folds the slug's in-body markers with abandon semantics

#### UC-TR-RETENTION-INDEPENDENT: Removed-todo purge window is independent of closed-session retention

#### UC-TR-SWEEP-SKIPS-NON-CHECKOUT: Retention sweep tolerates a non-checkout registry entry carrying a legacy todo store

#### UC-TR-REFUSES-LIVE-WORK: Removal refuses while live work holds the slug

#### UC-TR-OVERRIDE-RECORDED: A deliberate override removes anyway and is recorded

#### UC-TR-CLAIM-SURVIVES-ON-TOMBSTONE: The released claim is recorded, never silently discarded

#### UC-TR-RELEASES-REMOVER-BINDING: Removing its own Todo frees the claimant to drive another

#### UC-TR-REMOVED-SLUG-WRITE-REFUSED: An artifact write to a removed slug names the recoverable state

#### UC-TR-REMOVE-CLEANS-PENDING-MARKERS: Removal retires its pending documentation markers

#### UC-TR-DEFERRED-WORKTREE-RECLAIM: Removal releases the working location before bulk reclamation

### Cross-context references

- `operations` — removal is submitted as a receipt-backed durable operation whose outcome delivery `local/projects/teleclaude/spec/feature/agent_runtime/durable-operation-outcomes` owns; the CLI returns the receipt without waiting, and structured refusal payloads survive the operation boundary.

- `agent_runtime` — the delivered-slug cleanup cascade invokes the host `git` toolchain to tear down worktree and branches; remote branch deletion uses a short timeout and tolerates network failure.

## Known caveats

- A removal directive carrying a declared human decision executes unconditionally: the claimant neither verifies the involvement nor defends its todo (`general/policy/leadership` rule 12).
- Removal is recoverable only inside the retention window. Once routine maintenance purges the removed entry, retained lifecycle state, current artifacts, and artifact version history are permanently deleted.
- Reactivation is identity-addressed, not slug-addressed. A slug may have multiple retained removed entries over time, and a live same-slug entry blocks reactivation.

- Removing a Todo that is still a pending snippet's only deliverer after its co-owners delivered removes the whole snippet, including text that describes the delivered co-owners' work.

- Documentation abandonment and the tombstone form one fail-closed lifecycle transition. The caller commits exact-path documentation changes before reporting removal success and retains sufficient durable evidence to restore them on reactivation; any uncompensated failure faults instead of leaving a successful tombstone with foreign or uncommitted edits.
- Purge-time docs reconciliation is commit-gated. A dirty candidate snippet on a fresh pass leaves `pending_purge_paths` empty and the entry retained. A failed commit or verification failure leaves `pending_purge_paths` populated so the next sweep can distinguish sweep-owned residue from foreign edits.
- Removing a delivered Todo is not part of this surface; removal targets active or icebox entries only. Delivered work stays in git history (integration commits and merged branches on `main` are untouched).

- A holder is not removable: it sits outside the todo lifecycle, and removal targets todos only. Children are removed individually, no cascade runs in either direction, and a holder whose children have all been retired simply stops rendering while its row and frozen artifacts remain as evidence of the split.

- Artifact reads addressed to a slug whose every entry is removed resolve to that slug's most recently removed retained entry and return its retained content until purge; a view that already holds a retained entry's durable identity reads that entry directly. Lifecycle checks that decide what a Todo holds never resolve to a removed entry; a successor Todo that reuses the slug starts with none of a removed entry's artifacts. The removed-state refusal applies to artifact writes. The live-work guard reads sessions and operations from the daemon store, so a removal issued while the daemon store is unavailable fails rather than proceeding unguarded.

- The remote branch delete uses a short timeout and is non-fatal — a slow or unreachable origin will not block the operation from reporting completed, but may leave a stale remote branch that must be cleaned up out of band.

- The receipt-backed dispatch means the removal returns before the cascade has executed.
