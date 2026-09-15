---
visibility: public
number: 91
date: 2026-09-15
description: Preserve parking before candidate publication and block the drain on unresolved repository-root finalization after publication.
---

# Published Candidate Finalization Blocks the Drain — ADR

## Context

ADR-0076 keeps unrelated deliveries moving by parking a candidate whose conflict
or content-gate failure cannot be resolved before that candidate reaches
origin/main. ADR-0090 introduces a later finalization boundary: the integration
worktree first publishes and confirms candidate code, then repository-root main
synchronizes that commit, folds its documentation, passes the final gate, and
publishes the delivery SHA.

After the first push, canonical main already contains the candidate code. Parking
cannot withdraw it without rewriting shared history, and every later candidate
would inherit the same unresolved repository-root finalization state.

## Decision

Park-and-drain remains authoritative until candidate publication. An unresolved
textual conflict or content-gate failure before the first push parks the candidate
and its dependents while independent work continues.

Once the candidate push is confirmed on origin/main, that candidate becomes the
current finalization obligation. A repository-root synchronization, marker fold,
residual gate, final content gate, publication, or confirmation failure blocks
the drain until resolved. The candidate is not parked and no later candidate is
dequeued. Delivery remains unrecorded until the folded repository-root SHA is
confirmed.

## Consequences

- Pre-publication failures retain the throughput behavior selected by ADR-0076.
- Post-publication failures remain loud and recoverable but temporarily stop the
  queue.
- Canonical main never accumulates code from several non-delivered candidates
  behind one unresolved documentation finalization.
- The integrator cannot abandon a candidate after its first push; it must finish
  repository-root finalization or recover the shared main state under a later
  explicit decision.
- Dirty-main ownership and conflict resolution remain the only intelligence
  steps; deterministic gates, folding, publication, confirmation, and delivery
  recording stay machine-owned.

## Alternatives Considered

Parking after candidate publication was rejected because the candidate code is
already present on origin/main and cannot be isolated from later candidates.

Continuing to publish later candidate commits while postponing delivery records
was rejected because canonical state and lifecycle state would diverge for an
unbounded set of todos.

Rewriting origin/main to withdraw the candidate was rejected because it makes
routine recovery destructive and unsafe under concurrent delivery.
