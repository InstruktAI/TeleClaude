---
visibility: public
number: 90
date: 2026-09-15
description: Finalize a confirmed integration-worktree push by synchronizing, folding, and publishing repository-root main before recording delivery.
---

# Root Fold Finalizes a Pushed Candidate — ADR

## Context

Documentation is authored, committed, and indexed on repository-root main.
Candidate code is prepared in the integration worktree. ADR-0089 correctly
selected repository-root main as the sole marker-fold surface, but it also moved
candidate application ahead of the first canonical push and described one
combined push from the repository root.

The existing state machine already has a durable candidate-push and confirmation
boundary. Keeping that boundary makes the transition smaller and gives
repository-root synchronization one concrete remote commit to incorporate before
folding. The delivery record can remain withheld until repository-root main is
folded and its later push is confirmed, so ADR-0065 still places every content
decision before the push that completes delivery.

## Decision

Integrated delivery uses two machine-owned pushes. The integration worktree
pushes the prepared candidate commit to origin/main and the machine confirms that
commit. Repository-root main then synchronizes with origin/main, retaining its
committed documentation state. The machine reconciles the candidate slug only on
repository-root main, runs the residual and content gates there, pushes the
resulting repository-root head, and confirms that final commit. Only the final
confirmed repository-root SHA is recorded as the todo delivery commit.

Repository-root dirt, split history, or merge conflicts suspend finalization at
the existing integration blocker surface. The integrator agent resolves those
obstructions and re-enters the machine; it does not decide or perform marker
folding.

## Consequences

- Candidate publication and delivery completion are distinct durable boundaries.
- The candidate code may exist on origin/main while its todo remains
  non-delivered; dependency release waits for the final repository-root push.
- Marker reconciliation has one authoritative filesystem and one applied fold.
  Crash recovery may repeat the operation as an idempotent no-op.
- The integration worktree retains its existing candidate push and rejection
  recovery, reducing the implementation change.
- Repository-root synchronization and dirty-main clearance happen after the
  candidate push and before marker folding.
- The final recorded delivery SHA contains both the candidate and the folded
  documentation state.

## Alternatives Considered

Applying the candidate to repository-root main before any push was rejected
because it discards the existing durable candidate-push boundary and requires a
new root-assembly transaction with additional conflict and crash state.

Folding after the first push and recording that first SHA as delivered was
rejected because documentation could remain pending after delivery became
durable.

Folding in the integration worktree was rejected because repository-root main is
the documentation authority and may contain committed markers absent from the
worktree.
