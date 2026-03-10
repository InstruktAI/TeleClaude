# Requirements: mirror-runtime-isolation

This artifact was reconstructed during build from the approved plan, review findings,
and DOR report because the original `requirements.md` was missing from the worktree.

## Goal

- Isolate mirror reconciliation from the daemon control plane without losing
  canonical mirror identity or steady-state convergence.

## Scope

- In scope:
  - Canonical transcript allowlist enforcement for discovery and real-time mirror generation.
  - Pruning previously indexed non-canonical mirror rows.
  - Thread-isolated reconciliation with structured completion metrics.
  - Exact source identity keyed by canonical transcript path.
  - Empty-transcript tombstones and canonical backfill for convergence.
  - Separate roadmap tracking for `/todos/integrate` receipt-backing work.
- Out of scope:
  - Moving mirrors to a separate SQLite database unless the A5 measurement gate fails.
  - Bundling `/todos/integrate` receipt-backing changes into this mirror delivery.

## Success Criteria

- Discovery invariant: only canonical transcripts enter reconciliation and mirror generation.
- Identity invariant: mirror updates are keyed by canonical source identity, not fallback-derived ids.
- Runtime isolation invariant: bulk reconciliation runs off the daemon event loop.
- Convergence invariant: steady-state reconciliation approaches zero processed work.
- Empty-transcript invariant: empty transcripts converge via tombstones instead of perpetual churn.
- Storage decision invariant: any DB split remains conditional on measured pressure, not speculation.
- Workflow boundary invariant: `/todos/integrate` receipt-backing remains a separate tracked workstream.

## Constraints

- Keep containment and correctness incrementally mergeable with rollback boundaries.
- Preserve real-time event-driven mirror generation while moving bulk reconciliation off the event loop.
- Skip transcripts without authoritative session context; do not fall back to lossy derived ids.
- Prefer tests and executable verification over comments or surface reads.

## Risks

- The A5 measurement gate requires deployed reconciliation cycles; the A6 DB-split decision cannot be closed inside this worktree alone.
- Existing mirror rows created before canonical allowlisting can pollute metrics until prune and backfill land together.
