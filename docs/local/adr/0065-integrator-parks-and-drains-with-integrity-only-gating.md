---
visibility: public
number: 65
date: 2026-07-08
description: The integrator delivers by park-and-drain with integrity-only pre-push gating; its authority ends at the push, and post-push steps only confirm, record, and clean up.
---

# Integrator Parks and Drains, with Integrity-Only Gating — ADR

## Context

The integration state machine is the sole writer of canonical `origin/main`,
consuming finalize-ready candidates in FIFO order. Its documented model: halt
the entire queue on any undeliverable candidate (no later candidate dequeued
while a conflict stands), a pre-push content gate running the full lint
composition, and a post-push delivery-confirmation gate proving candidate
content landed by re-squash-merging the frozen candidate branch tip against
`origin/main` and requiring an empty diff.

Operational evidence exposed three structural problems:

- The containment probe false-negatives whenever a delivery legitimately
  transforms content relative to the frozen candidate tip — the delivered-snippet
  fold rewrites doc state in the squash, and integrator follow-up commits
  resolving repo-wide invariants edit the candidate's own lines. Byte-identity
  of the stale tip becomes unprovable, and the machine wedges in an infinite
  PUSH_SUCCEEDED ↔ PUSH_REJECTED loop. Because the push has already happened,
  the gate can withhold nothing — it can only loop.
- Halt-on-first-failure starves all delivery behind one problematic candidate,
  even though candidates are squash-merged onto _current_ `origin/main`:
  integrity does not depend on delivery order beyond the declared dependency
  DAG, and total conflict-resolution work is order-invariant.
- Full quality gating at integration re-blocks on issues already validated in
  worktree isolation (style findings, flaky/racing tests), conflating quality
  with integrity and stalling functional deliveries.

Forces in play: delivery is recorded only after a confirmed push, so dependents
never build on unpushed work; worktree gates guarantee branch integrity at
finalize time but structurally cannot guarantee merge integrity (two green
branches do not compose into a green merge); and the integrator's authority
window is dequeue → push — after the push, nothing is withholdable.

## Decision

The integrator delivers by **park-and-drain with integrity-only gating**, and
its governance acts only inside its authority window:

- **Park-and-drain.** An undeliverable candidate is parked, dependency-safe:
  nothing downstream of a parked candidate is delivered. Draining continues
  through the remaining deliverable candidates, and the drain ends with an
  explicit report of every parked candidate and why. Parking is always loud,
  never silent.
- **Integrity blocks; quality reports.** The pre-push gate blocks only on
  integrity: merge breakage, shared-invariant ratchets, and candidate
  cleanliness (the branch carries only its own slug's work). Quality findings —
  style, formatting, flaky tests — are reported and filed as follow-up work,
  never fixed inline and never blocking.
- **Deterministic verification triggers.** A clean squash-merge trusts upstream
  worktree validation and runs no test suite. Conflict resolution or an
  integrator-authored commit creates a state no worktree ever tested and
  triggers a required test run. A drain-end batch test over the merged result
  closes the semantic-merge gap at one suite run per drain, bisecting on red to
  identify and park the culprit.
- **Failure discrimination by baseline probe.** A failure at integration is
  re-run against main without the candidate: failing on the baseline means
  systemic (report and file, do not block the drain); failing only with the
  candidate means candidate-local (park); candidate-local on a clean merge is a
  merge-induced integrity event.
- **Authority ends at the push.** Post-push steps are confirmation — a ref
  check that the frozen, actually-pushed commit landed on `origin/main` —
  followed by delivery bookkeeping and cleanup. No post-push step exercises
  content judgment or withholds delivery.

## Consequences

- One wedged candidate no longer stalls the queue; throughput and blocker
  resolution decouple.
- The delivered ⟺ confirmed-on-origin/main invariant is preserved: dependents
  are still unblocked only after the push is confirmed.
- The containment false-negative class disappears: confirmation checks the
  commit that was pushed, not a content re-derivation from a stale tip.
- Parked candidates age: main advances while they wait, concentrating rebase
  work on the already-problematic item. Accepted as the price of throughput.
- The semantic-merge window is covered by batch testing instead of per-candidate
  suite runs — one run per drain instead of N.
- Feature-spec scenarios binding halt-forever semantics and
  containment-by-re-squash confirmation change meaning.

## Alternatives Considered

- **Halt-FIFO (status quo).** Maximizes immediacy of blocker resolution.
  Rejected: integrity does not require delivery order beyond the dependency
  DAG, and one stuck candidate starves all delivery.
- **Full gating per candidate (lint + suite pre-push, blocking).** Strongest
  per-candidate guarantee. Rejected: re-imposes already-passed quality gates as
  blockers, costs N suite runs per drain, and lets flaky failures wedge the
  pipeline on issues integration does not own.
- **Pure trust (no verification at integration).** Rejected: merge integrity is
  structurally unverifiable upstream — two green branches do not compose.
- **Post-push content containment (status quo confirmation).** Rejected: a
  delivery legitimately transforms content (snippet fold, invariant fix
  commits), so byte-identity of the frozen candidate tip is unprovable — and
  post-push judgment cannot withhold anything; it can only loop.

## Status

Superseded in part by ADR-0076.
