---
visibility: public
number: 89
date: 2026-09-15
description: Use repository-root main as the sole documentation-fold and final-push surface for candidate delivery.
---

# Delivery Folds on Repository-Root Main — ADR

## Context

Documentation preparation is authored and committed on repository-root main,
whose generated index is the authoritative view consumed by agents. Candidate
code is prepared in isolated worktrees, and the integration worktree may be
based on an older origin/main that does not contain committed documentation
material already present on repository-root main.

ADR-0085 addressed that mismatch by publishing ahead-only repository-root state
before candidate selection and keeping the candidate fold in the integration
worktree. That ordering still admits a later documentation commit during a
multi-candidate drain, and it maintains two physical views of documentation for
a responsibility owned by one source.

The delivery fold must remain automatic, slug-scoped, and fail closed when the
repository root cannot be mutated safely. ADR-0065 still requires all content
mutation to finish before the confirmed push that ends the integrator authority
window.

## Decision

Repository-root main is the sole documentation reconciliation surface for
integrated candidate delivery. The integration worktree prepares the candidate
commit without folding documentation. At candidate finalization, the integrator
synchronizes repository-root main, applies the prepared candidate there, folds
that slug pending documentation there, runs the residual-marker and content
gates against that final tree, and pushes the resulting head to origin/main.
Only confirmation of that push permits the delivery record.

Committed ahead-only repository-root state is not published merely to seed an
integration worktree. It remains part of the authoritative final assembly.
When repository-root main cannot be synchronized or safely mutated, candidate
delivery waits with the existing dirty-main evidence.

Settled-marker recovery continues to reconcile repository-root main directly as
a separate idempotent operation without rewriting the historical delivery
record.

## Consequences

- Every normal candidate delivery has one marker fold over the complete
  authoritative documentation set.
- Documentation and candidate code reach origin/main through one final push, so
  the live contract cannot lead or trail the recorded delivery.
- Integration-worktree folds, duplicate reconciliation commits, and entry-time
  publication of ahead-only main disappear.
- Repository-root dirt or split history can delay a candidate because the final
  delivery tree must be safe to mutate. This is the accepted cost of using the
  authoritative documentation source.
- The recorded delivery commit is the confirmed repository-root head containing
  the candidate and its folded documentation.

## Alternatives Considered

Publishing repository-root documentation before candidate selection and folding
in the integration worktree was rejected because one integration call can drain
multiple candidates while repository-root documentation continues to advance.

Folding in both trees was rejected because it creates duplicate commits and
allows the two reconciliation plans to disagree.

Copying or independently reconstructing repository-root marker state inside the
integration worktree was rejected because it creates a second documentation
authority and requires completeness checks that disappear when one authoritative
tree performs the fold.
