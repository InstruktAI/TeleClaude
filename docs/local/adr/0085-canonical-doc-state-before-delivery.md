---
visibility: internal
number: 85
date: 2026-09-11
description: Publish committed repo-root documentation state before candidate selection, keep one candidate delivery fold, and repair exceptional settled-marker divergence as a separate operation.
---

# Canonical Documentation State Before Delivery — ADR

## Context

Pending documentation may be committed on repo-root main while the integration
worktree is based on origin/main. Treating an ahead-only repository root as ready
for candidate selection lets the integration worktree fold a view that lacks
those pending carriers. Synchronizing the repository root after the candidate is
terminal can then reveal material that the only candidate fold never saw.

The earlier two-tree delivery path happened to reconcile this material in the
repository root, but it also created duplicate reconciliation commits, split
local and remote history, and paired delivery compensation with a different
tree from the reconciliation that reached origin/main. ADR-0065 additionally
keeps candidate-delivery authority bounded by the push: post-push confirmation
must not become a second content decision for that candidate.

## Decision

Make committed repository-root documentation visible to candidate delivery
before candidate selection. When the integration checkpoint is idle and
repo-root main is ahead of, but not behind, origin/main, the integrator publishes
that state through its canonical-main writer path and confirms it before
dequeuing a candidate. The integration worktree then starts from the updated
origin/main and remains the sole owner of the candidate's delivery fold.

Treat settled-marker divergence discovered later as a separate recovery
operation, never as a continuation of the original candidate delivery. The
integrator reconciles only the faulted slug against a synchronized, safe
repository root, commits and publishes that cleanup through the same
canonical-main writer path, and leaves the original delivery record and commit
provenance unchanged.

## Consequences

- Normal delivery retains one reconciliation receipt, one reconciliation tree,
  and one delivery commit whose documentation view includes committed repo-root
  preparation state.
- Ahead-only repo-root commits reach origin/main before candidate work begins,
  so a publication or content-gate failure stops dequeue instead of becoming a
  post-delivery documentation divergence.
- The divergence sweep gains a bounded recovery consumer for exceptional or
  bypassed paths; repair stays slug-scoped and idempotent.
- A recovery cleanup is a distinct canonical-main commit and is not part of the
  original delivery commit. Audit readers must distinguish delivery provenance
  from later convergence of documentation state.
- An integration drain may pause before candidate selection while ahead-only
  repo-root state is published and confirmed.

## Alternatives Considered

Restoring the second repository-root fold inside candidate delivery was rejected
because it recreates duplicate commits, split history, and a compensation handle
bound to the wrong tree.

Moving the normal fold to the repository root after candidate push was rejected
because it removes documentation from the isolated delivery commit and turns
post-push confirmation into content mutation after the integrator can still
withhold delivery.

Keeping maintenance detection-only was rejected because it identifies an
impossible settled state while leaving every supported reconciliation door
closed.

## Status

Superseded by ADR-0089.
